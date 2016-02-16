# coding: utf-8
from django.db import models
from django.db.models.signals import class_prepared
from django.apps import AppConfig
from .models import (bind_update_priority_handlers,
                     update_priority_on_m2m_changed,
                     update_priority_on_post_save)


class RuleModelConfig(AppConfig):
    name = 'rule_model'
    label = 'rule_model'

    def ready(self):
        class_prepared.connect(bind_update_priority_handlers,
                               dispatch_uid='bind_update_priority_handlers')
