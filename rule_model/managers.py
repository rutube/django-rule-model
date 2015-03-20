# coding: utf-8
from django.db import models


class BaseRuleManager(models.Manager):
    """ Базовые класы для отдельных часто встречающихся случаев таргетирования
    """
    # для переопределения в наследниках
    def get_filtered_query(self, **kwargs):
        return self.get_query_set()

    # Поля, которые фильтруются запросом (для переопределения в наследниках)
    exclude_check = ()

    def match_best(self, **kwargs):
        """ Выбирает наиболее продходящее правило """
        selected_rule = None
        rules = self.get_filtered_query(**kwargs)

        for current_rule in rules.iterator():
            if current_rule.match(exclude_check=self.exclude_check, **kwargs):
                # флаг говорящий о том, что домен совпал не полностью,
                # а по шаблону домена, например *.rutube.ru.
                # Такое совпадение менее приоритетно, чем точное
                by_pattern = getattr(current_rule, "domain_match_by_pattern", False)
                if selected_rule:
                    # если до этого у нас что-то уже совпадало по шаблону домена
                    if current_rule.priority < selected_rule.priority:
                        # и если приоритет предыдущего совпадения больше,
                        # то возвращаем предыдущее совпадение
                        return selected_rule
                    elif not by_pattern:
                        # если текущее правило совпало не по домену, то оно
                        # приоритетней предыдушего совпадения - возвращаем его
                        return current_rule
                else:
                    # если до этого не было совпадения
                    if by_pattern:
                        # и текущее правило совпало по шаблону домена, то не
                        # спешим вернуть его сразу, а запоминаем, чтобы сравнить
                        # совпадения доменов с другими правилами с тем же
                        # приоритетом
                        selected_rule = current_rule
                    else:
                        return current_rule
        return selected_rule