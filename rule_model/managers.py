# coding: utf-8
from django.db import models


class BaseRuleManager(models.Manager):
    """ Базовый класс менеджера правил.
    """
    # для переопределения в наследниках
    def get_filtered_query(self, **kwargs):
        return self.get_query_set()

    # Поля, которые фильтруются запросом (для переопределения в наследниках)
    exclude_check = ()

    def match_best(self, **kwargs):
        """ Выбирает наиболее продходящее правило """
        rules = self.get_filtered_query(**kwargs)
        for current_rule in rules.iterator():
            if current_rule.match(exclude_check=self.exclude_check, **kwargs):
                return current_rule