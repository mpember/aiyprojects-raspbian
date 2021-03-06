#!/usr/bin/env python3
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run a recognizer using the Google Assistant Library.

The Google Assistant Library has direct access to the audio API, so this Python
code doesn't need to record audio. Hot word detection "OK, Google" is supported.

The Google Assistant Library can be installed with:
    env/bin/pip install google-assistant-library==0.0.2

It is available for Raspberry Pi 2/3 only; Pi Zero is not supported.
"""

import logging
import subprocess
import sys
import time
import json

import os.path
import pathlib2 as pathlib
import configargparse

import google.oauth2.credentials

# from google.assistant.library import Assistant
# from google.assistant.library.file_helpers import existing_file
# from google.assistant.library.device_helpers import register_device
from google.assistant.library.event import EventType

from aiy.assistant import auth_helpers
from aiy.assistant.library import Assistant
from aiy.board import Board, Led
from aiy.voice import tts

from modules.kodi import KodiRemote
from modules.music import Music, PodCatcher
from modules.readrssfeed import ReadRssFeed
from modules.mqtt import MQTTSwitch
from modules.powercommand import PowerCommand

_configPath = os.path.expanduser('~/.config/voice-assistant.ini')
_settingsPath = os.path.expanduser('~/.config/settings.ini')
_remotePath = "https://argos.int.mpember.net.au/rpc/get/remotes"

_kodiRemote = KodiRemote(_settingsPath)
_music = Music(_settingsPath)
_podCatcher = PodCatcher(_settingsPath)
_readRssFeed = ReadRssFeed(_settingsPath)
_MQTTSwitch = MQTTSwitch(_settingsPath, _remotePath)

try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


WARNING_NOT_REGISTERED = """
    This device is not registered. This means you will not be able to use
    Device Actions or see your device in Assistant Settings. In order to
    register this device follow instructions at:

    https://developers.google.com/assistant/sdk/guides/library/python/embed/register-device
"""

def _createPID(pid_file='voice-recognizer.pid'):

    pid_dir = '/run/user/%d' % os.getuid()

    if not os.path.isdir(pid_dir):
        pid_dir = '/tmp'

    logging.info('PID stored in ' + pid_dir)

    file_name = os.path.join(pid_dir, pid_file)
    with open(file_name, 'w') as pid_file:
        pid_file.write("%d" % os.getpid())

def _volumeCommand(change):

    """Changes the volume and says the new level."""

    res = subprocess.check_output(r'amixer get Master | grep "Front Left:" | sed "s/.*\[\([0-9]\+\)%\].*/\1/"', shell=True).strip()
    try:
        logging.info('volume: %s', res)
        if change == 0 or change > 10:
            vol = change
        else:
            vol = int(res) + change

        vol = max(0, min(100, vol))
        if vol == 0:
            tts.say('Volume at %d %%.' % vol)

        subprocess.call('amixer -q set Master %d%%' % vol, shell=True)
        tts.say('Volume at %d %%.' % vol)

    except (ValueError, subprocess.CalledProcessError):
        logging.exception('Error using amixer to adjust volume.')

def process_event(assistant, led, event):

    global _cancelAction

    logging.info(event)
    if event.type == EventType.ON_START_FINISHED:
        led.state = Led.OFF  # Ready.
        print('Say "OK, Google" then speak, or press Ctrl+C to quit...')
        

    elif event.type == EventType.ON_CONVERSATION_TURN_STARTED:
        led.state = Led.ON

    elif event.type == EventType.ON_ALERT_STARTED and event.args:
        logging.warning('An alert just started, type = ' + str(event.args['alert_type']))
        assistant.stop_conversation()

    elif event.type == EventType.ON_ALERT_FINISHED and event.args:
        logging.warning('An alert just finished, type = ' + str(event.args['alert_type']))

    elif event.type == EventType.ON_RECOGNIZING_SPEECH_FINISHED and event.args:

        _cancelAction = False
        text = event.args['text'].lower()

        logging.info('You said: ' + text)

        if text == '':
            assistant.stop_conversation()

        elif _music.getConfirmPlayback() == True:
            assistant.stop_conversation()
            if text == 'yes':
                _music.command('podcast', 'CONFIRM')
            else:
                _music.setConfirmPlayback(False)
                _music.setPodcastURL(None)

#        elif text.startswith('music '):
#            assistant.stop_conversation()
#            _music.command('music', text[6:])

        elif text.startswith('podcast '):
            assistant.stop_conversation()
            _music.command('podcast', text[8:], _podCatcher)
            if _music.getConfirmPlayback() == True:
                assistant.start_conversation()

        elif text.startswith('play ') and text.endswith(' podcast'):
            assistant.stop_conversation()
            _music.command('podcast', text[5:][:-8], _podCatcher)
            if _music.getConfirmPlayback() == True:
                assistant.start_conversation()

        elif text.startswith('play ') and text.endswith(' podcasts'):
            assistant.stop_conversation()
            _music.command('podcast', text[5:][:-9], _podCatcher)
            if _music.getConfirmPlayback() == True:
                assistant.start_conversation()

        elif text.startswith('radio '):
            assistant.stop_conversation()
            _music.command('radio', text[6:])

        elif text.startswith('headlines '):
            assistant.stop_conversation()
            _readRssFeed.run(text[10:])

        elif text.startswith('turn on ') or text.startswith('turn off ') or text.startswith('turn down ') or text.startswith('turn up '):
            assistant.stop_conversation()
            _MQTTSwitch.run(text[5:])

        elif text.startswith('switch to channel '):
            assistant.stop_conversation()
            _kodiRemote.run('tv ' + text[18:])

        elif text.startswith('switch '):
            assistant.stop_conversation()
            _MQTTSwitch.run(text[7:])

        elif text.startswith('media center '):
            assistant.stop_conversation()
            _kodiRemote.run(text[13:])

        elif text.startswith('kodi ') or text.startswith('cody '):
            assistant.stop_conversation()
            _kodiRemote.run(text[5:])

        elif text.startswith('play the next episode of '):
            assistant.stop_conversation()
            _kodiRemote.run('play unwatched ' + text[25:])

        elif text.startswith('play next episode of '):
            assistant.stop_conversation()
            _kodiRemote.run('play unwatched ' + text[21:])

        elif text.startswith('play the most recent episode of '):
            assistant.stop_conversation()
            _kodiRemote.run('play unwatched ' + text[32:])

        elif text.startswith('play most recent episode of '):
            assistant.stop_conversation()
            _kodiRemote.run('play unwatched ' + text[28:])

        elif text.startswith('play unwatched ') or text.startswith('play tv series '):
            assistant.stop_conversation()
            _kodiRemote.run(text)

        elif text.startswith('play the lastest recording of '):
            assistant.stop_conversation()
            _kodiRemote.run('play recording ' + text[31:])

        elif text.startswith('play the recording of '):
            assistant.stop_conversation()
            _kodiRemote.run('play recording ' + text[23:])

        elif text.startswith('play recording of '):
            assistant.stop_conversation()
            _kodiRemote.run('play recording ' + text[18:])

        elif text.startswith('play recording '):
            assistant.stop_conversation()
            _kodiRemote.run(text)

        elif text.startswith('tv '):
            assistant.stop_conversation()
            _kodiRemote.run(text)

        elif text in ['power off','shutdown','shut down','self destruct']:
            assistant.stop_conversation()
            PowerCommand('shutdown')

        elif text in ['restart', 'reboot']:
            assistant.stop_conversation()
            PowerCommand('reboot')

        elif text == 'volume up':
            assistant.stop_conversation()
            _volumeCommand(10)

        elif text == 'volume down':
            assistant.stop_conversation()
            _volumeCommand(-10)

        elif text == 'volume maximum':
            assistant.stop_conversation()
            _volumeCommand(100)

        elif text == 'volume mute':
            assistant.stop_conversation()
            _volumeCommand(0)

        elif text == 'volume reset':
            assistant.stop_conversation()
            _volumeCommand(80)

        elif text == 'volume medium':
            assistant.stop_conversation()
            _volumeCommand(50)

        elif text == 'volume low':
            assistant.stop_conversation()
            _volumeCommand(30)

        elif text in ['brightness low', 'set brightness low']:
            assistant.stop_conversation()
            led.brightness(0.4)

        elif text in ['brightness medium', 'set brightness medium']:
            assistant.stop_conversation()
            led.brightness(0.7)

        elif text in ['brightness high', 'set brightness high', 'brightness full', 'set brightness full']:
            assistant.stop_conversation()
            led.brightness(1)

    elif event.type == EventType.ON_RESPONDING_FINISHED:
        assistant.stop_conversation()
        logging.info('EventType.ON_RESPONDING_FINISHED')

    elif event.type == EventType.ON_MEDIA_TRACK_LOAD:
        assistant.stop_conversation()
        logging.info('EventType.ON_MEDIA_TRACK_LOAD')
        logging.info(event.args)

    elif event.type == EventType.ON_MEDIA_TRACK_PLAY:
        assistant.stop_conversation()
        logging.info('EventType.ON_MEDIA_TRACK_PLAY')
        logging.info(event.args)

    elif event.type == EventType.ON_END_OF_UTTERANCE:
        led.state = Led.PULSE_QUICK

    elif (event.type == EventType.ON_CONVERSATION_TURN_FINISHED
          or event.type == EventType.ON_CONVERSATION_TURN_TIMEOUT
          or event.type == EventType.ON_NO_RESPONSE):
        led.state = Led.OFF

    elif event.type == EventType.ON_ASSISTANT_ERROR and event.args and event.args['is_fatal']:
        logging.info('EventType.ON_ASSISTANT_ERROR')
        sys.exit(1)

    elif event.type == EventType.ON_ASSISTANT_ERROR:
        logging.info('EventType.ON_ASSISTANT_ERROR')

    elif event.args:
        logging.info(event.type)
        logging.info(event.args)

    else:
        logging.info(event.type)

def main():

    parser = configargparse.ArgParser(
        default_config_files=[_configPath],
        description="Act on voice commands using Google's speech recognition")
    parser.add_argument('-L', '--language', default='en-GB',
                        help='Language code to use for speech (default: en-GB)')
    parser.add_argument('-p', '--pid-file', default='voice-recognizer.pid',
                        help='File containing our process id for monitoring')
    parser.add_argument('--trigger-sound', default=None,
                        help='Sound when trigger is activated (WAV format)')
    parser.add_argument('--brightness-max', type=int, default=1,
                        help='Maximum LED brightness')
    parser.add_argument('--brightness-min', type=int, default=1,
                        help='Minimum LED brightness')
    parser.add_argument('-d', '--daemon', action='store_true',
                        help='Daemon Mode')

    args = parser.parse_args()

    _createPID(args.pid_file)

    if args.daemon is True or sys.stdout.isatty() is not True:
        _podCatcher.start()
        logging.info("Starting in daemon mode")
    else:
        logging.info("Starting in non-daemon mode")

    credentials = auth_helpers.get_assistant_credentials()
    with Board() as board, Assistant(credentials) as assistant:
        logging.info('Setting brightness to %d %%' % args.brightness_max)
        logging.info(board.led)
        logging.info('Setting brightness to %d %%' % args.brightness_max)
        # led.brightness(0.2)

        for event in assistant.start():
            process_event(assistant, board.led, event)

if __name__ == '__main__':
    try:
        if sys.stdout.isatty():
            logging.basicConfig(
                level=logging.INFO,
                format="%(levelname)s:%(name)s:%(message)s"
            )
        else:
            logging.basicConfig(
                level=logging.WARNING,
                format="%(levelname)s:%(name)s:%(message)s"
            )

        main()
    except:
        pass

