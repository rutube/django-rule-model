# coding: utf-8
from django.db import models


class BaseRuleManager(models.Manager):
    """ Базовый класс менеджера правил.
    """
    def filter_active(self):
        return self.filter(is_active=True)

    def get_filtered_query(self, *args, **kwargs):
        """ Наивная реализация фильтрации объектов правил.

        Может переопределяться в наследниках.
        """
        return self.filter_active().filter(*args, **kwargs).order_by('-priority')

    # Поля, которые фильтруются запросом и не требуют дополнительной
    # проверки методом match() модели
    exclude_check = tuple()

    def match_best(self, *args, **kwargs):
        """ Выбирает наиболее продходящее правило """
        rules = self.get_filtered_query(*args, **kwargs)
        for current_rule in rules.iterator():
            if current_rule.match(exclude_check=self.exclude_check, **kwargs):
                return current_rule

    def match_all(self, *args, **kwargs):
        """ Генератор, возвращает все подходящие правила в порядке приоритета
        """
        rules = self.get_filtered_query(*args, **kwargs)
        for current_rule in rules.iterator():
            if current_rule.match(exclude_check=self.exclude_check, **kwargs):
                yield current_rule