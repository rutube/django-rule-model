# coding: utf-8
import six
from collections import Mapping, OrderedDict


class Validation(Mapping):
    """ Результат валидации правила.

    В булевом контексте возвращает True, если все проверки пройдены успешно.
    Результаты каждой конкретной проверки доступны по ключу.
    """
    def __init__(self, mapping):
        self.__checkers = OrderedDict(mapping)
        self.__validation = {}

    def __getitem__(self, item):
        try:
            return self.__validation[item]
        except KeyError:
            self.__validation[item] = bool(self.__checkers[item]())
            return self.__validation[item]

    def __iter__(self):
        return iter(self.__checkers)

    def __len__(self):
        return len(self.__checkers)

    def __nonzero__(self):
        return all(six.itervalues(self))

    __bool__ = __nonzero__

