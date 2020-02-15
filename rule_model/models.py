# coding: utf-8
from __future__ import unicode_literals
import operator
from functools import partial

from django import VERSION
from django.conf import settings
from django.db import models
from django.dispatch import receiver
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from rule_model.managers import BaseRuleManager
from rule_model.signals import rule_deactivated_auto_signal
from rule_model.validation import Validation


def get_rel(m2m):
    if VERSION < (1, 9):
        return m2m.rel
    return m2m.remote_field

def get_model(remote_field):
    if VERSION < (1, 9):
        return remote_field.to
    return remote_field.model


class PriorityOrderingAbstractModel(models.Model):
    """ Миксин для моделей, приоритезируемых в зависимости от состояния полей.

    Для использования  класса модели должно быть определено свойство
    priority_sorted_fields содержащее список полей модели, перечисленных в
    порядке убываниях их важности при определении приоритета

    Например: priority_sorted_fields = ['ref', 'cats', 'uid']
    """

    # пересчитывается каждый раз автоматически при сохранении модели
    priority = models.IntegerField(_('приоритет'), blank=True, default=0)

    # поля модели, отсортированные в порядке убывания их приоритета
    # должны быть переопределены в конкретном классе модели
    priority_sorted_fields = tuple()

    class Meta(object):
        abstract = True

    def check_attr(self, field):
        """ Умеет проверять на непустоту стандартные значения полей модели
        (включая m2m)
        :param field: имя поля модели
        :return: пустое/непустое
        """
        field_value = getattr(self, field)

        checker = self.get_field_checker(field)
        return checker(field_value)

    def get_field_checker(self, field):
        """ Возвращает подходящий чекер в зависимости от типа поля """
        try:
            field_object, model, direct, is_m2m = self._meta.get_field_by_name(field)
        except models.FieldDoesNotExist:
            field_object, model, direct, is_m2m = (None, None, None, False)

        if is_m2m:
            return self.check_qs
        if field_object and isinstance(field_object, models.NullBooleanField):
            return self.check_strict
        return self.check_default

    def check_qs(self, value):
        return value.exists()

    def check_default(self, value):
        return bool(value)

    def check_strict(self, value):
        return value is not None

    def need_strict_check(self, field):
        """ Говорит, нужно ли строго проверять филд на пустоту или достаточно
        проверки его булевого значения
        """
        try:
            return isinstance(self._meta.get_field_by_name(field)[0],
                              models.NullBooleanField)
        except models.FieldDoesNotExist:
            return False

    @property
    def priority_bin(self):
        """ Приоритет в виде битовой маски
        """
        mask = []
        for fld in self.priority_sorted_fields:
            checker = getattr(self, "_check_priority_%s" % fld, self.check_attr)
            if hasattr(self, fld) and checker(fld):
                mask.append('1')
            else:
                mask.append('0')
        return ''.join(mask)

    @property
    def priority_dec(self):
        """ Приоритет в десятичном виде """
        return int(self.priority_bin, 2)

    def update_priority(self):
        """ Обновляет приоритет и корректно сохраняет новое значение
        в процессе сохранения состояния модели в БД.

        По умолчанию 1 в приоритет выставляется в случае, если у атрибута
        есть непустое значение. Для всех полей это поведение определяется в
        функции check_attr,
        Если необходимо изменить это поведение для одного поля,
        то можно создать у модели поле _check_priority_<field_name>
        """
        p = self.priority_dec
        if p == self.priority:
            return
        self.priority = p
        type(self).objects.filter(pk=self.pk).update(priority=self.priority)


def update_priority_on_post_save(sender, instance, **kwargs):
    """ Обновляет значение приоритета по сигналу сохранения модели с
    приоритетами.
    """
    instance.update_priority()


def update_priority_on_m2m_changed(sender, action, instance, **kwargs):
    """ Обновляет значение приоритета по сигналу изменения полей m2m модели с
    приоритетами.
    """
    if (action in ('post_clear', 'post_add', 'post_remove') and
            hasattr(instance, 'update_priority')):
        instance.update_priority()


def update_priority_on_m2m_model_delete(sender, instance, *args, **kwargs):
    """ Обновляем приоритет при удалении связанных по m2m объекто. m2m_changed
    в этом случае не срабатывает
    """
    if hasattr(instance, "_need_update_priority"):
        for v in instance._need_update_priority.values():
            for m in v:
                old_priority = m.priority
                m.update_priority()
                # Если у нас изменился приоритет - значит удалился последний из
                # связей с m2m. Это может привести к тому, что правило начнет
                # неявно таргетироваться на большее количество записей. Поэтому
                # деактивируем его, если это разрешено настройками
                if old_priority != m.priority and m.deactivate_on_clean_related_m2m:
                    m.is_active = False
                    m.save()
                    rule_deactivated_auto_signal.send(sender, rule=m, related=instance)


def update_priority_fabric(m2m):
    """ Фабрика для обработчиков сигналов удаления связанных по m2m объектов.
    Возвращает функцию, которая будет собирать информацию о связанных правилах,
    которым нужно обновить приоритет после удаления
    """
    def save_need_update_priority(sender, instance, *args, **kwargs):
        if not hasattr(get_rel(m2m).related_model, "update_priority"):
            return
        if not hasattr(instance, "_need_update_priority"):
            instance._need_update_priority = {}
        to_update = list(get_rel(m2m).related_model.objects.filter(**{m2m.name: instance}))
        instance._need_update_priority[get_rel(m2m).related_model] = to_update
    return save_need_update_priority


@receiver(models.signals.class_prepared,
          dispatch_uid='bind_update_priority_handlers')
def bind_update_priority_handlers(sender, **kwargs):
    """ Подключает сигналы для пересчёта приоритетов при обновление моделей,
    поддерживающих приоритеты.
    """
    if hasattr(sender, 'update_priority'):
        models.signals.post_save.connect(
            update_priority_on_post_save, sender=sender,
            dispatch_uid='update_priority_on_post_save')
        for m2m in sender._meta.many_to_many:
            if m2m.name in sender.priority_sorted_fields:
                models.signals.m2m_changed.connect(
                    update_priority_on_m2m_changed, sender=get_rel(m2m).through,
                    dispatch_uid='update_priority_on_m2m_changed')
                models.signals.pre_delete.connect(
                    update_priority_fabric(m2m), sender=get_model(get_rel(m2m)), weak=False,
                    dispatch_uid='%s_save_need_update_priority' % get_rel(m2m).through.__name__)
                models.signals.post_delete.connect(
                    update_priority_on_m2m_model_delete, sender=get_model(get_rel(m2m)),
                    dispatch_uid='update_priority_on_m2m_model_delete')


class AbstractRuleModel(PriorityOrderingAbstractModel):
    """ Абстрактная модель приоритезированного правила.
    """
    is_active = models.BooleanField(_("активно"), default=True)
    objects = BaseRuleManager()

    deactivate_on_clean_related_m2m = getattr(
        settings, "RULE_MODEL_DEACTIVATE_ON_CLEAN_RELATED_M2M", True)

    @cached_property
    def params_to_check(self):
        return self._params_to_check or [f.name for f in self._meta.fields]

    def get_param_checker(self, f, exclude_check=set()):
        """ Возвращает генератор валидаторов для параметров правила
        """
        if f in exclude_check:
            return lambda a: True
        else:
            try:
                return getattr(self, "check_%s" % f)
            except AttributeError:
                return partial(operator.eq, getattr(self, f))

    def match(self, exclude_check=set(), **kwargs):
        """ Функция проверки подходит ли правило под указанные в параметра
        условия.

        Реализация по умолчанию, методы для проверки параметров генерируются
        автоматически на основе простого сравнения.

        @param exclude_check: множество, содержит в себе проверки, которые
            можно исключить. Полезен в случаях, когда мы точно знаем, что
            правило пройдет какую-то проверку.
        @param kwargs: параметры фильтрации
        @return: объект self.Validation
        """
        checkers = []
        for f in self.params_to_check:
            checker = self.get_param_checker(f, exclude_check)
            checkers.append((f, partial(checker, kwargs.get(f))))
        return Validation(checkers)

    class Meta(PriorityOrderingAbstractModel.Meta):
        abstract = True
