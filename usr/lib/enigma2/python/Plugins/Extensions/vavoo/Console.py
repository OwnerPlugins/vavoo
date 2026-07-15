#!/usr/bin/python
# -*- coding: utf-8 -*-
# RAED & mfaraj57 &  (c) 2018
# mod Lululla 20251113

from __future__ import print_function
from enigma import eConsoleAppContainer
from Screens.Screen import Screen
from Components.Label import Label
from Components.ActionMap import ActionMap

from Screens.MessageBox import MessageBox
from enigma import getDesktop

from . import PY3

import gettext
_ = gettext.gettext


def getDesktopSize():
    s = getDesktop(0).size()
    return (s.width(), s.height())


def isHD():
    desktopSize = getDesktopSize()
    return desktopSize[0] == 1280


class Console(Screen):
    # Framed dialog card matching UpdatePopup.xml's size/style, rather than
    # a near-fullscreen console, so the install flow feels like one
    # continuous popup instead of two different-looking screens.
    if isHD():
        skin = '''<screen name="VavooInstallerConsole" position="center,center" size="800,460" title="Command execution..." backgroundColor="#ff0a0510" flags="wfNoBorder">
            <eLabel position="0,0" size="800,460" backgroundColor="#0a0510" zPosition="-10"/>
            <eLabel position="0,0"   size="800,1" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,459" size="800,1" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,0"   size="1,460" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="799,0" size="1,460" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="1,1" size="26,3" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1,1" size="3,26" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="773,1" size="26,3" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="796,1" size="3,26" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1,457" size="26,3" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1,433" size="3,26" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="773,457" size="26,3" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="796,433" size="3,26" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel text="Command execution..." font="Regular;22" size="740,32" position="30,22" foregroundColor="#f0e0ff" backgroundColor="#0a0510" zPosition="4"/>
            <eLabel position="30,58" size="740,1" backgroundColor="#3a1a5a" zPosition="4"/>
            <eLabel position="30,68" size="740,300" backgroundColor="#0e0518" zPosition="1"/>
            <eLabel position="30,68" size="740,1" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="30,367" size="740,1" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="30,68" size="1,300" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="769,68" size="1,300" backgroundColor="#2a0a3a" zPosition="2"/>
            <widget name="text" position="44,80" size="712,276" backgroundColor="#0e0518" foregroundColor="#e0d0f0" font="Console;16" transparent="1" zPosition="5"/>
            <eLabel position="30,384" size="740,1" backgroundColor="#3a1a5a" zPosition="4"/>
            <eLabel position="30,408" size="24,24" backgroundColor="#c0392b" zPosition="4"/>
            <eLabel text="Cancel" position="62,408" zPosition="2" size="180,24" font="Regular;16" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel position="310,408" size="24,24" backgroundColor="#9970bb" zPosition="4"/>
            <eLabel text="Hide/Show" position="342,408" zPosition="2" size="180,24" font="Regular;16" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel position="590,408" size="24,24" backgroundColor="#27ae60" zPosition="4"/>
            <eLabel text="Restart GUI" position="622,408" zPosition="2" size="150,24" font="Regular;16" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
        </screen>'''
    else:
        skin = '''<screen name="VavooInstallerConsole" position="center,center" size="1200,690" title="Command execution..." backgroundColor="#ff0a0510" flags="wfNoBorder">
            <eLabel position="0,0" size="1200,690" backgroundColor="#0a0510" zPosition="-10"/>
            <eLabel position="0,0"   size="1200,2" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,688" size="1200,2" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,0"   size="2,690" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="1198,0" size="2,690" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="2,2" size="38,4" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="2,2" size="4,38" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1159,2" size="38,4" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1194,2" size="4,38" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="2,684" size="38,4" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="2,648" size="4,38" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1159,684" size="38,4" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel position="1194,648" size="4,38" backgroundColor="#8b2fc9" zPosition="3"/>
            <eLabel text="Command execution..." font="Regular;33" size="1110,48" position="45,33" foregroundColor="#f0e0ff" backgroundColor="#0a0510" zPosition="4"/>
            <eLabel position="45,87" size="1110,2" backgroundColor="#3a1a5a" zPosition="4"/>
            <eLabel position="45,102" size="1110,450" backgroundColor="#0e0518" zPosition="1"/>
            <eLabel position="45,102" size="1110,2" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="45,550" size="1110,2" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="45,102" size="2,450" backgroundColor="#2a0a3a" zPosition="2"/>
            <eLabel position="1153,102" size="2,450" backgroundColor="#2a0a3a" zPosition="2"/>
            <widget name="text" position="66,120" size="1068,414" backgroundColor="#0e0518" foregroundColor="#e0d0f0" font="Console;24" transparent="1" zPosition="5"/>
            <eLabel position="45,576" size="1110,2" backgroundColor="#3a1a5a" zPosition="4"/>
            <eLabel position="45,612" size="36,36" backgroundColor="#c0392b" zPosition="4"/>
            <eLabel text="Cancel" position="93,612" zPosition="2" size="270,36" font="Regular;24" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel position="465,612" size="36,36" backgroundColor="#9970bb" zPosition="4"/>
            <eLabel text="Hide/Show" position="513,612" zPosition="2" size="270,36" font="Regular;24" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel position="885,612" size="36,36" backgroundColor="#27ae60" zPosition="4"/>
            <eLabel text="Restart GUI" position="933,612" zPosition="2" size="225,36" font="Regular;24" halign="left" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
        </screen>'''

    # Keep only the most recent lines so the buffer (and the Label holding
    # it) don't grow unbounded over a long-running install.
    MAX_LINES = 200

    def __init__(
            self,
            session,
            title='Console',
            cmdlist=None,
            finishedCallback=None,
            closeOnSuccess=False,
            showStartStopText=True,
            skin=None):
        Screen.__init__(self, session)
        self.finishedCallback = finishedCallback
        self.closeOnSuccess = closeOnSuccess
        self.showStartStopText = showStartStopText
        # "Console" is a generic, widely-reused screen name across many
        # Enigma2 plugins - some installed skins/themes ship their own
        # <screen name="Console"> override, which the skin engine prefers
        # over this class's inline skin string. Use a name unique to this
        # plugin so our own skin always wins, unless a caller explicitly
        # asked for a specific skin variant.
        self.skinName = [skin, 'VavooInstallerConsole'] if skin else [
            'VavooInstallerConsole']
        self.errorOcurred = False
        self._text_buffer = ''
        # Plain Label, not ScrollLabel: ScrollLabel's setText() depends on
        # a pageHeight computed during skin binding that doesn't reliably
        # come out non-zero on every image, which left it silently blank
        # (see the same issue on the update popup's changelog).
        self['text'] = Label('')
        self['key_red'] = Label(_('Cancel'))
        self['key_green'] = Label(_('Hide/Show'))
        self['key_blue'] = Label(_('Restart'))
        self["actions"] = ActionMap(
            ["WizardActions", 'ColorActions'],
            {
                "ok": self.cancel,
                "red": self.cancel,
                "green": self.toggleHideShow,
                "blue": self.restartenigma,
                "exit": self.cancel,
            }, -1
        )

        self.newtitle = title == 'Console' and _(
            'Console') or title  # Fixed: Added _ function
        self.cmdlist = isinstance(cmdlist, list) and cmdlist or [cmdlist]
        self.cancel_msg = None
        self.onShown.append(self.updateTitle)
        self.container = eConsoleAppContainer()
        self.run = 0
        self.finished = False
        try:
            self.container.appClosed.append(self.runFinished)
            self.container.dataAvail.append(self.dataAvail)
        except BaseException:
            self.container.appClosed_conn = self.container.appClosed.connect(
                self.runFinished)
            self.container.dataAvail_conn = self.container.dataAvail.connect(
                self.dataAvail)
        self.onLayoutFinish.append(self.startRun)

    def _setText(self, text):
        self._text_buffer = text
        self['text'].setText(self._text_buffer)

    def _appendText(self, text):
        self._text_buffer += text
        lines = self._text_buffer.split('\n')
        if len(lines) > self.MAX_LINES:
            self._text_buffer = '\n'.join(lines[-self.MAX_LINES:])
        self['text'].setText(self._text_buffer)

    def updateTitle(self):
        self.setTitle(self.newtitle)

    def startRun(self):
        if self.showStartStopText:
            self._setText(_('Execution progress\n\n'))
        print('[Console] executing in run', self.run,
              ' the command:', self.cmdlist[self.run])
        print("[Console] Executing command:", self.cmdlist[self.run])
        if self.container.execute(self.cmdlist[self.run]):
            self._setText(self.cmdlist[self.run])
            self.runFinished(-1)

    def runFinished(self, retval):
        if retval:
            self.errorOcurred = True
            self.show()

        self.run += 1

        if self.run != len(self.cmdlist):
            if self.container.execute(self.cmdlist[self.run]):
                self.runFinished(-1)
            return  # Exit early

        # All commands have finished
        self.show()
        self.finished = True

        if self.cancel_msg:
            self.cancel_msg.close()

        if self.showStartStopText:
            self._appendText('Execution finished!!')

        if self.finishedCallback:
            self.finishedCallback()

        if self.errorOcurred or not self.closeOnSuccess:
            self._appendText('\nPress OK or Exit to abort!')
            self['key_red'].setText('Exit')
            self['key_green'].setText('')
        else:
            self.closeConsole()

    def toggleHideShow(self):
        if self.finished:
            return
        if self.shown:
            self.hide()
        else:
            self.show()

    def cancel(self):
        if self.finished:
            self.closeConsole()
        else:
            self.cancel_msg = self.session.openWithCallback(
                self.cancelCallback,
                MessageBox,
                _('Cancel execution?'),
                type=MessageBox.TYPE_YESNO,
                default=False)

    def cancelCallback(self, ret=None):
        self.cancel_msg = None
        if ret:
            try:
                self.container.appClosed.remove(self.runFinished)
                self.container.dataAvail.remove(self.dataAvail)
            except BaseException:
                self.container.appClosed_conn = None
                self.container.dataAvail_conn = None
            self.container.kill()
            self.close()

    def closeConsole(self):
        if self.finished:
            try:
                self.container.appClosed.remove(self.runFinished)
                self.container.dataAvail.remove(self.dataAvail)
            except BaseException:
                self.container.appClosed_conn = None
                self.container.dataAvail_conn = None
            self.close()
        else:
            self.show()

    def dataAvail(self, str):
        if PY3:
            data = str.decode()
        else:
            data = str
        print("[Console] Data received: ", data)
        self._appendText(data)

    def restartenigma(self):
        from Screens.Standby import TryQuitMainloop
        self.session.open(TryQuitMainloop, 3)
