# TODO:
#  - support more RFC5545 icalendar properties,
#  - better integration in plone ui (content tabs),
#  - save ical settings at all and in annotation
#  - cleanup,
#  - tests

from Products.CMFPlone.utils import safe_unicode
from plone.app.event import base
from plone.event.interfaces import IEventAccessor
from plone.event.utils import is_date, date_to_datetime
from zope.container.interfaces import INameChooser
import icalendar
import datetime
import random
import transaction
import urllib2


def ical_import(container, ics_resource, event_type):
    cal = icalendar.Calendar.from_ical(ics_resource)
    events = cal.walk('VEVENT')

    def _get_prop(prop, item, _as_unicode=True):
        ret = None
        if prop in item:
            if _as_unicode:
                ret = safe_unicode(item.decoded(prop))
            else:
                ret = item.decoded(prop)
        return ret

    count = 0
    for item in events:
        start = _get_prop('DTSTART', item)
        end = _get_prop('DTEND', item)
        if not end:
            duration = _get_prop('DURATION', item)
            if duration:
                end = start + duration
            else:
                end = start

        timezone = getattr(getattr(start, 'tzinfo', None), 'zone', None) or\
                base.default_timezone(container)

        whole_day = False
        if is_date(start) and is_date(end):
            # All day / whole day events
            # End must be same type as start (RFC5545, 3.8.2.2)
            whole_day = True
            if start<end:
                # RFC5545 doesn't define clearly, if all day events should have
                # a end date one day after the start day at 0:00.
                # Internally, we handle all day events with start=0:00,
                # end=:23:59:59, so we substract one day here.
                end = end-datetime.timedelta(days=1)
            start = base.dt_start_of_day(date_to_datetime(start))
            end = base.dt_end_of_day(date_to_datetime(end))
        assert(isinstance(start, datetime.datetime))
        assert(isinstance(end, datetime.datetime))

        title = _get_prop('SUMMARY', item)
        description = _get_prop('DESCRIPTION', item)

        # TODO: better use plone.api, from which some of the code here is
        # copied
        content_id = str(random.randint(0, 99999999))

        container.invokeFactory(event_type,
                                id=content_id,
                                title=title,
                                description=description,
                                start=start,
                                end=end,
                                timezone=timezone)
        content = container[content_id]

        event = IEventAccessor(content)
        event.whole_day = whole_day

        # Archetypes specific code
        if getattr(content, 'processForm', False):
            # Will finish Archetypes content item creation process,
            # rename-after-creation and such
            content.processForm()

        # Create a new id from title
        chooser = INameChooser(container)
        new_id = chooser.chooseName(title, content)
        transaction.savepoint(optimistic=True)
        content.aq_parent.manage_renameObject(content_id, new_id)

        count += 1

    return {'count': count}


from zope.interface import Interface
from zope import schema
from plone.app.event import messageFactory as _
from plone.namedfile.field import NamedFile

class IIcalendarImportSettings(Interface):

    event_type = schema.Choice(
        title = _(u'Event Type'),
        vocabulary = 'plone.app.event.EventTypes',
        required = True
    )

    ical_url = schema.URI(
        title = _(u'Icalendar URL'),
        required = False
    )

    ical_file = NamedFile(
        title = _(u"Icalendar File"),
        required = False
    )

    sync_strategy = schema.Choice(
        title = _(u"Synchronization Strategy"),
        vocabulary = 'plone.app.event.SynchronizationStrategies',
        required = True
    )


from Products.statusmessages.interfaces import IStatusMessage
from z3c.form import button
from z3c.form import form, field

class IcalendarImportSettingsForm(form.Form):

    fields = field.Fields(IIcalendarImportSettings)
    ignoreContext = True

    def updateWidgets(self):
        super(IcalendarImportSettingsForm, self).updateWidgets()

    @button.buttonAndHandler(u'Save and Import')
    def handleSave(self, action):
        data, errors = self.extractData()
        if errors:
            return False

        ical_file = data['ical_file']
        if ical_file:
            ical_resource = ical_file.data
            ical_import_from = ical_file.filename
        else:
            ical_url = data['ical_url']
            ical_resource = urllib2.urlopen(ical_url, 'rb').read()
            ical_import_from = ical_url
        event_type = data['event_type']

        import_metadata = ical_import(
            self.context,
            ics_resource=ical_resource,
            event_type=event_type
        )

        count = import_metadata['count']

        IStatusMessage(self.request).addStatusMessage(
            "%s events imported from %s" % (count, ical_import_from),
            'info')
        redirect_url = self.context.absolute_url()
        self.request.response.redirect(redirect_url)

    @button.buttonAndHandler(u'Cancel')
    def handleCancel(self, action):
        redirect_url = self.context.absolute_url()
        self.request.response.redirect(redirect_url)

from plone.z3cform.layout import wrap_form
IcalendarImportSettingsFormView = wrap_form(IcalendarImportSettingsForm)
