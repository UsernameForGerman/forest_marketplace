# -*- coding: utf-8 -*-
import datetime
from optparse import make_option

import django.utils.timezone
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError
from django.utils.encoding import force_unicode
from django.utils.translation import override
from market.models import EmailTemplate, Advertisement


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option(
            '--no-update',
            action='store_true',
            default=False,
            help=u'Отсылать, но не сохранять изменения в БД'
        ),
        make_option(
            '--fake',
            action='store_true',
            default=False,
            help=u'Ничего не отсылать и не сохранять, только показывать'
        ),
        make_option(
            '--to-email',
            action='store',
            help=u'Отсылать на этот адрес, а не владельцам объявлений'
        ),
        make_option(
            '--user-id',
            action='store',
            help=u'Только для пользователя с этим id'
        ),
    )

    help = force_unicode(
        '''Для рассылки напоминаний. Использование:
            wood/manage.py send_reminders''')
    requires_model_validation = False

    def handle(self, *args, **options):

        def send_remind_email(reminds, site, obj_template, email_owner=None, to_email=None):
            context = {'ads': reminds, 'site': site, 'user': email_owner}
            with override(reminds[0].owner.profile.language):
                obj_template.create_message(context, to=[to_email or email_owner.email]).send()

        filter_username = None
        if args:
            filter_username = args[0].decode('utf8')
        fake = options['fake']
        no_update = options['no_update']
        to_email = options['to_email']
        now = datetime.datetime.now()

        email_template_remind, created = EmailTemplate.objects.get_or_create(
            name_ru=settings.EMAIL_TEMPLATE_REMINDER)  # @UnusedVariable
        email_template_hidden, created = EmailTemplate.objects.get_or_create(
            name_ru=settings.EMAIL_TEMPLATE_ENTITY_HIDDEN)  # @UnusedVariable

        if not email_template_remind.subject or not email_template_remind.content:
            raise CommandError('Шаблон писем «%s» пуст. Останов.' % settings.EMAIL_TEMPLATE_REMINDER.encode('utf8'))
        if not email_template_hidden.subject or not email_template_hidden.content:
            raise CommandError(
                'Шаблон писем «%s» пуст. Останов.' % settings.EMAIL_TEMPLATE_ENTITY_HIDDEN.encode('utf8'))

        site = Site.objects.get_current()
        users_ids = Advertisement.get_public_objects().order_by('owner').values_list('owner', flat=True).distinct()
        for us in users_ids:
            reminds = list()
            email_owner = None
            reminds_hide = list()
            email_owner_hide = None

            queryset = Advertisement.get_public_objects().filter(owner_id=us)
            if filter_username:
                queryset = queryset.filter(owner__username=filter_username)
            if options['user_id']:
                queryset = queryset.filter(owner_id=options['user_id'])

            for entity in queryset:  # разрешённые к показу модератором и не скрытые по таймауту
                if entity.last_reminder_sent:
                    last_change_or_remind_time = max(entity.created, entity.last_reminder_sent)
                else:
                    last_change_or_remind_time = entity.created

                if entity.created.replace(tzinfo=None) + settings.HIDE_AFTER < now:
                    print 'Hiding for %r' % entity
                    if not fake:
                        entity.hidden_by_timeout = True
                        if entity.owner.profile.block_notifications:
                            entity.last_reminder_sent = django.utils.timezone.now()
                            reminds_hide.append(entity)
                        if not no_update:
                            entity.save()
                        email_owner_hide = entity.owner

                elif last_change_or_remind_time.replace(tzinfo=None) + settings.REMIND_AFTER < now:
                    if not entity.owner.profile.reminder_on:
                        continue
                    print 'Sending reminder for %r' % entity
                    if not fake:
                        entity.last_reminder_sent = django.utils.timezone.now()
                        if not no_update:
                            entity.save()
                        reminds.append(entity)
                        email_owner = entity.owner

            if reminds and (to_email or email_owner):
                send_remind_email(reminds, site, email_template_remind, email_owner, to_email)
            if reminds_hide and (to_email or email_owner_hide):
                send_remind_email(reminds_hide, site, email_template_hidden, email_owner_hide, to_email)
