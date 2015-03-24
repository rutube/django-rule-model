# coding: utf-8
from django.db import models
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from functools import partial
import operator
from rule_model.managers import BaseRuleManager


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
            sender = m2m.rel.through
            models.signals.m2m_changed.connect(
                update_priority_on_m2m_changed, sender=sender,
                dispatch_uid='update_priority_on_m2m_changed')


class AbstractRuleModel(PriorityOrderingAbstractModel):
    """ Абстрактная модель приоритезированного правила.
    """
    objects = BaseRuleManager()

    @property
    def params_to_check(self):
        while True:
            try:
                return self._params_to_check
            except AttributeError:
                self._params_to_check = [f.name for f in self._meta.fields]

    def match(self, check_all=False, exclude_check=set(), **kwargs):
        """ Функция проверки подходит ли правило под указанные в параметра
        условия.

        Реализация по умолчанию, методы для проверки параметров генерируются
        автоматически на основе простого сравнения.

        @param check_all: параметр, указывающий что нужно проверить все поля,
            прежде чем вернуть ответ. Если установлен в False, то возвращает
            False сразу как только какой-либо параметр не пройдет проверку.
        @param exclude_check: множество, содержит в себе проверки, которые
            можно исключить. Полезен в случаях, когда мы точно знаем, что
            правило пройдет какую-то проверку.
        @param kwargs: параметры фильтрации
        @return: True/False в зависимости от того, подходит объект для данных
            параметров или нет

        """
        # Убрать self.validation. Результатом вызова должет быть объект
        # validation, который ведёт себя как dict, а в булевом контекте выдает
        # True/False в зависимости от состояния ячеек.
        self.validation = {}
        result = True
        for f in self.params_to_check:
            if f in exclude_check or f not in kwargs:
                # пропускаем проверку, если она не требуется
                continue

            # Сравнивает занчание поля модели и переданного параметра
            default_checker = partial(operator.eq, getattr(self, f))

            checker = getattr(self, "check_%s" % f, default_checker)
            if checker(kwargs.get(f)):
                self.validation[f] = True
            else:
                self.validation[f] = False
                if check_all:
                    result = False
                else:
                    return False
        return result

    class Meta(PriorityOrderingAbstractModel.Meta):
        abstract = True