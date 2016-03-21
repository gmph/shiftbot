import StringIO
import json
import logging
import random
import urllib
import urllib2
import re
import requests
import datetime as dateTime
from datetime import timedelta, time, date, datetime
import time as Time

# For sending images:
from PIL import Image
import multipart

# For datastore of users and work status:
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext.db import stats

# Standard app engine imports:
from google.appengine.api import urlfetch
from google.appengine.ext import ndb
import webapp2

# Telegram API and Admin Settings:
# Add a file private.py to the directory with the following code:
#
# token = 'YOUR_AUTH_TOKEN'
# admin = YOUR_CHAT_ID
#
# Note that your chat_id should be an int and your token should be a string.

from private import token, admin
BASE_URL = 'https://api.telegram.org/bot' + token + '/'
ADMIN_ON = True # Admin sees admin view by default, not user view
ADMIN_ID = admin

# Data Conversion:

def getTextFromJson(json):
    return str(json.dumps(json))

def getJsonFromText(text):
    return json.loads(str(text))

# Datastore Models

class Shifts(db.Model):
    user_id = db.StringProperty(required=True)
    shift_list = db.StringProperty(required=True)

# Example Shift List:
# {
# 	"1": {
# 		"start": "1458552600",
# 		"end": "1458583200",
# 		"note": "Floor"
# 	},
# 	"2": {
# 		"start": "1458552600",
# 		"end": "1458583200",
# 		"note": "Back"
# 	}
# }

# Shift Functions

# Example Shift Dict:
# {
#     "start":"1458552600",
#     "end":"1458583200",
#     "note":"Floor"
# }

def addShift(user_id,new_shift_json):

    deleteAllPastShiftsForUser(user_id)

    new_shift_data = getJsonShiftsForUser(user_id)
    new_shift_index = len(new_shift_data)
    new_shift_properties = new_shift_json
    new_shift_data[str(new_shift_index)] = new_shift_properties

    if len(new_shift_data) > 7:
        return False

    else:
        snew = Shifts(key_name=str(user_id),
                      user_id=str(user_id),
                      shift_list=json.dumps(new_shift_data))
        snew.put()
        return True

def createShiftDict(start,end,note):
    # start - unix time for start of shift
    # end   - unix time for end of shift
    # note  - user-created note for this shift
    return json.loads(json.dumps({
        "start" : str(round(int(float(start)))),
        "end" : str(round(int(float(end)))),
        "note" :str(note)
    }))

def getReadableShiftsForUser(user_id):
    deleteAllPastShiftsForUser(user_id)
    user_shifts = getJsonShiftsForUser(user_id)
    unsorted_pairs = []
    if len(user_shifts) > 0:
        try:
            for shift, shift_data in user_shifts.items():
                unsorted_pairs.append({ "start" : shift_data['start'], "end" : shift_data['end'] })
            sorted_startend = sorted(unsorted_pairs, key=lambda x: int(round(float(x['start']))))
            readable_string = "";
            for pairs in sorted_startend:
                readable_string += "\n`" + getReadableShiftFromUnix(pairs['start'],pairs['end']) + "`"
        except:
            readable_string = "\n`No shifts to display`"
    else:
        readable_string = "\n`No shifts to display`"

    return readable_string

def deleteAllPastShiftsForUser(user_id):
    user_shifts = getJsonShiftsForUser(user_id)
    cleaned_dict = {}
    for shift, shift_data in user_shifts.items():
        if shift_data['end'] > Time.time():
            cleaned_dict.update( { shift : createShiftDict(shift_data['start'], shift_data['end'], shift_data['note'])} )

    snew = Shifts(key_name=str(user_id),
                  user_id=str(user_id),
                  shift_list=json.dumps(cleaned_dict))
    snew.put()

def deleteAllShiftsForUser(user_id):
    user_shifts = getJsonShiftsForUser(user_id)
    cleaned_dict = {}

    snew = Shifts(key_name=str(user_id),
                  user_id=str(user_id),
                  shift_list=json.dumps(cleaned_dict))
    snew.put()

def getJsonShiftsForUser(user_id):
    shifts_for_user_key = db.Key.from_path('Shifts', str(user_id))
    try:
        shifts_for_user = (db.get(shifts_for_user_key)).shift_list
    except:
        return json.loads(json.dumps({}))
    try:
        return json.loads(shifts_for_user)
    except:
        return json.loads(json.dumps({}))

def checkIfUserExists(user_id):
    shifts_for_user_key = db.Key.from_path('Shifts', str(user_id))
    try:
        shifts_for_user = (db.get(shifts_for_user_key))
    except:
        return False
    if shifts_for_user:
        return True
    else:
        return False

# Date Functions

def getReadableShiftFromUnix(start_unix_string,end_unix_string):
    start_datetime = datetime.fromtimestamp(int(round(float(start_unix_string))))
    end_datetime = datetime.fromtimestamp(int(round(float(end_unix_string))))
    return start_datetime.strftime('%b. %d, %H:%M') + ' - ' + end_datetime.strftime('%H:%M') + start_datetime.strftime(' (%A)')

def getDateForDayOfWeekN(dayname,n=1):
    today = datetime.today()
    day_of_week = today.weekday()
    days_till_next_monday = (7*n) - day_of_week
    next_monday = today + timedelta(days=days_till_next_monday)

    days_of_week = {
        "Monday" : 0,
        "Tuesday" : 1,
        "Wednesday" : 2,
        "Thursday" : 3,
        "Friday" : 4,
        "Saturday" : 5,
        "Sunday" : 6,
    }

    date_to_return = None

    for x in range(0, 7):
        day_x = (next_monday + timedelta(days=x))
        if dayname == list_of_week_day_names[day_x.weekday()]:
            date_to_return = day_x.date()

    return date_to_return

list_of_week_day_names = ["Mo","Tu","We","Th","Fr","Sa","Su"]


# Short-Term Conversation Dictionary

conversations = {}

positiveResponses = ['y','yes','yeah','yup','yah','ya','mhmm','yep','yip','go','do it', 'mhm','I would']

# Telegram Helpers

def getKeyboardFromList(buttons):
    return {
        'keyboard' : buttons,
        'resize_keyboard' : True,
        'one_time_keyboard' : True,
        'selective' : False
    }

# Default Status and Handlers:

class MeHandler(webapp2.RequestHandler):
    def get(self):
        urlfetch.set_default_fetch_deadline(60)
        self.response.write(json.dumps(json.load(urllib2.urlopen(BASE_URL + 'getMe'))))

class GetUpdatesHandler(webapp2.RequestHandler):
    def get(self):
        urlfetch.set_default_fetch_deadline(60)
        self.response.write(json.dumps(json.load(urllib2.urlopen(BASE_URL + 'getUpdates'))))

class SetWebhookHandler(webapp2.RequestHandler):
    def get(self):
        urlfetch.set_default_fetch_deadline(60)
        url = self.request.get('url')
        if url:
            self.response.write(json.dumps(json.load(urllib2.urlopen(BASE_URL + 'setWebhook', urllib.urlencode({'url': url})))))

# Fetch message when posted:

class WebhookHandler(webapp2.RequestHandler):
    def post(self):
        urlfetch.set_default_fetch_deadline(60)
        body = json.loads(self.request.body)
        logging.info('request body:')
        logging.info(body)
        self.response.write(json.dumps(body))

        update_id = body['update_id']
        message = body['message']
        message_id = message.get('message_id')
        date = message.get('date')
        text = message.get('text')
        fr = message.get('from')
        chat = message['chat']
        chat_id = chat['id']
        fr_username = fr.get('username')
        fr_firstname = fr.get('first_name')
        fr_lastname = fr.get('last_name')

        if not text:
            text = ''
        else:
            text = ''.join([i if ord(i) < 128 else '*' for i in text])

        # Message Sending Functions:

        def fwdToMe(frchatid,msgid):
            resp = urllib2.urlopen(BASE_URL + 'forwardMessage', urllib.urlencode({
                'chat_id': str(ADMIN_ID), # @grahammacphee's chat_id
                'from_chat_id': frchatid,
                'message_id': msgid,
            }))

        def replyWithBot(tochatid,msg):
            message = "Direct from Graham: " + msg
            resp = urllib2.urlopen(BASE_URL + 'sendMessage', urllib.urlencode({
                'chat_id': tochatid,
                'text': message.encode('utf-8'),
            }))

        def reply(msg=None, img=None, parsemode=None, markup=None):
            if msg:
                if markup:
                    markup = markup
                else:
                    markup = { 'hide_keyboard' : True }
                resp = urllib2.urlopen(BASE_URL + 'sendMessage', urllib.urlencode({
                    'chat_id': str(chat_id),
                    'text': msg.encode('utf-8'),
                    'disable_web_page_preview': 'true',
                    'parse_mode' : "Markdown", # str(parsemode),
                    'reply_markup' : json.dumps(markup)
                })).read()
            elif img:
                resp = multipart.post_multipart(BASE_URL + 'sendPhoto', [
                    ('chat_id', str(chat_id)),
                ], [
                    ('photo', 'image.jpg', img),
                ])
            else:
                logging.error('No message or image specified.')
                resp = None

            logging.info('Send response:')
            logging.info(resp)

        def userExists():
            try:
                test_user = conversations[str(chat_id)]
            except:
                return False
            return True

        try:
            step_name = conversations[str(chat_id)][0]
        except:
            step_name = "start_new"

        try:
            previous_text = conversations[str(chat_id)][1]
        except:
            previous_text = ""

        try:
            data = conversations[str(chat_id)][2]
        except KeyError:
            data = {}

        # shift_data = createShiftDict("1458552600","1458583200","Floor")
        #
        # addShift(chat_id,shift_data)
        #
        # reply(json.dumps(getJsonShiftsForUser(chat_id)))

        # Manage wait steps:
        if "_wait" in step_name:
            step_name = step_name.replace('_wait','')

        hasCancelled = False

        # Normal steps:

        if 'cancel' in text.lower():
            step_name = 'start_existing'
            data = {}
            reply("What would you like to do?",markup=getKeyboardFromList([['Add a shift'],['Show my shifts'],['Delete all my shifts']]))
            hasCancelled = True

        if not(hasCancelled):

            # if step_name == 'start_new':
            #     if userExists():
            #         step_name = 'start_existing'
            #     else:
            #         reply("Nice to meet you! I'm a simple bot that can record work shifts for you.")
            #         reply("Would you like to add a shift?",markup=getKeyboardFromList([['I sure would!']]))
            #         step_name = 'listening_new_wait'

            # if step_name == 'listening_new':
            #     reply("Awesome! Let's add your first shift.")
            #     step_name = 'add_shift'

            if step_name == 'start_existing' or step_name == 'start_new':
                if 'add' in text.lower():
                    step_name = 'add_shift'
                elif 'show' in text.lower():
                    step_name = 'check_shift'
                elif 'delete' in text.lower():
                    step_name = 'delete_all'
                else:
                    reply("What would you like to do?",markup=getKeyboardFromList([['Add a shift'],['Show my shifts'],['Delete all my shifts']]))

            if step_name == 'add_shift':
                reply("Which week is your shift?",markup=getKeyboardFromList([['This week'],['Next week'],['The week after']]))
                step_name = 'add_shift_week_wait'

            if step_name == 'add_shift_week':
                if 'this week' in text.lower():
                    data.update({'new_shift' : { 'week' : 0 }})
                    reply("Great! Which day this week?",markup=getKeyboardFromList([['Mo','Tu','We','Th','Fr','Sa','Su']]))
                    step_name = 'add_shift_day_wait'
                elif 'next week' in text.lower():
                    data.update({'new_shift' : { 'week' : 1 }})
                    reply("Got it! Which day next week?",markup=getKeyboardFromList([['Mo','Tu','We','Th','Fr','Sa','Su']]))
                    step_name = 'add_shift_day_wait'
                elif 'the week after' in text.lower():
                    data.update({'new_shift' : { 'week' : 2 }})
                    reply("Thanks! Which day that week?",markup=getKeyboardFromList([['Mo','Tu','We','Th','Fr','Sa','Su']]))
                    step_name = 'add_shift_day_wait'
                else:
                    reply("Sorry, I didn't get that. Which week is your shift?",markup=getKeyboardFromList([['This week'],['Next week'],['The week after']]))
                    step_name = 'add_shift_week_wait'

            if step_name == 'add_shift_day':
                if text in list_of_week_day_names:
                    week_for_date = conversations[str(chat_id)][2]['new_shift']['week']
                    data['new_shift'].update({ 'date' : getDateForDayOfWeekN(text,week_for_date) })
                    reply('When is your shift on '+ data['new_shift']['date'].strftime('%b. %d') + '? \n(e.g. 15.30 - 17.30)')
                    step_name = 'add_shift_time_wait'
                else:
                    reply("Oops, I didn't understand that! Which day of the week is your shift?",markup=getKeyboardFromList([['Mo','Tu','We','Th','Fr','Sa','Su']]))
                    step_name = 'add_shift_day_wait'

            if step_name == 'add_shift_time':

                if len(text.replace(' ','').split('-')) == 2 and len(text.replace(' ','').split('-')[0].split('.')) == 2 and len(text.replace(' ','').split('-')[1].split('.')) == 2:

                    start_time_hours = text.replace(' ','').split('-')[0].split('.')[0]
                    start_time_minutes = text.replace(' ','').split('-')[0].split('.')[1]
                    time_for_shift_start = dateTime.time(int(start_time_hours), int(start_time_minutes))
                    date_for_shift_start = conversations[str(chat_id)][2]['new_shift']['date']
                    datetime_for_shift_start = dateTime.datetime.combine(date_for_shift_start, time_for_shift_start)
                    unix_for_shift_start = str(int(round(Time.mktime(datetime_for_shift_start.timetuple()))))

                    end_time_hours = text.replace(' ','').split('-')[1].split('.')[0]
                    end_time_minutes = text.replace(' ','').split('-')[1].split('.')[1]
                    time_for_shift_end = dateTime.time(int(end_time_hours), int(end_time_minutes))
                    date_for_shift_end = conversations[str(chat_id)][2]['new_shift']['date']
                    datetime_for_shift_end = dateTime.datetime.combine(date_for_shift_end, time_for_shift_end)
                    unix_for_shift_end = str(int(round(Time.mktime(datetime_for_shift_end.timetuple()))))

                    if addShift(str(chat_id),createShiftDict(unix_for_shift_start,unix_for_shift_end,"")):
                        reply('Saved! Here are your latest shifts:')
                        reply(getReadableShiftsForUser(str(chat_id)))
                    else:
                        reply('You can only add up to 7 shifts in this demo. Delete all shifts to start again.')
                    step_name = 'start_existing'
                    reply("What would you like to do?",markup=getKeyboardFromList([['Add a shift'],['Show my shifts'],['Delete all my shifts']]))
                else:
                    reply("Please use 24 hour time (e.g. 15.30 - 17.30). What time is your shift?")
                    step_name = 'add_shift_time_wait'

            if step_name == "check_shift":
                reply('Here are your latest shifts:')
                reply(getReadableShiftsForUser(str(chat_id)))
                step_name = 'start_existing'
                reply("What would you like to do?",markup=getKeyboardFromList([['Add a shift'],['Show my shifts'],['Delete all my shifts']]))

            if step_name == "delete_all":
                reply('Delete all of these?',markup=getKeyboardFromList([['Cancel','Delete them \xF0\x9F\x99\x80']]))
                reply(getReadableShiftsForUser(str(chat_id)),markup=getKeyboardFromList([['Cancel','Delete them \xF0\x9F\x99\x80']]))
                step_name = 'delete_all_confirm_wait'

            if step_name == "delete_all_confirm":
                if "delete" in text.lower():
                    deleteAllShiftsForUser(str(chat_id))
                    reply('Your shifts have been reset!')
                else:
                    reply("No worries! Your shifts have not been deleted.")
                step_name = 'start_existing'
                reply("What would you like to do?",markup=getKeyboardFromList([['Add a shift'],['Show my shifts'],['Delete all my shifts']]))

        hasCancelled = False

        if text == 'reset' and chat_id == ADMIN_ID:
            global conversations
            conversations = {}
        else:
            global conversations
            conversations.update({str(chat_id): [step_name,text,data]})

            # For debugging:
            # reply('`You are on step: '+step_name+'`', parsemode="Markdown")
            # reply('`'+str(conversations[str(chat_id)])+'`', parsemode="Markdown")


app = webapp2.WSGIApplication([
    ('/me', MeHandler),
    ('/updates', GetUpdatesHandler),
    ('/set_webhook', SetWebhookHandler),
    ('/webhook', WebhookHandler),
], debug=True)
