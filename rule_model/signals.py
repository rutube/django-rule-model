# coding: utf-8
from django.dispatch import Signal

rule_deactivated_auto_signal = Signal(providing_args=['rule', 'related'])