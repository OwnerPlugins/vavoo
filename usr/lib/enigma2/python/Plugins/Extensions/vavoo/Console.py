#!/usr/bin/python
# -*- coding: utf-8 -*-
# RAED & mfaraj57 &  (c) 2018
# mod Lululla 20251113

from __future__ import print_function
from enigma import eConsoleAppContainer
from Screens.Screen import Screen
from Components.Label import Label
from Components.ActionMap import ActionMap
from Components.ScrollLabel import ScrollLabel

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
    if isHD():
        skin = '''<screen position="17,center" size="1245,681" title="Command execution..." backgroundColor="#ff0a0510" flags="wfNoBorder">
            <eLabel position="0,0" size="1245,681" backgroundColor="#0a0510" zPosition="-10"/>
            <eLabel position="0,0" size="1245,1" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,680" size="1245,1" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,0" size="1,681" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="1244,0" size="1,681" backgroundColor="#bf5fff" zPosition="2"/>
            <widget name="text" position="9,48" size="1237,587" backgroundColor="#0e0518" foregroundColor="#e0d0f0" font="Console;24"/>
            <eLabel text="Command execution..." font="Regular;30" size="1000,40" position="8,3" foregroundColor="#f0e0ff" backgroundColor="#0a0510" zPosition="4"/>
            <eLabel position="10,674" size="165,5" backgroundColor="#c0392b" zPosition="1"/>
            <eLabel position="238,674" size="165,5" backgroundColor="#9970bb" zPosition="1"/>
            <eLabel position="1068,674" size="165,5" backgroundColor="#27ae60" zPosition="1"/>
            <eLabel text="Cancel" position="10,646" zPosition="2" size="165,30" font="Regular;24" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel text="Hide/Show" position="238,646" zPosition="2" size="165,30" font="Regular;24" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel text="Restart GUI" position="1068,646" zPosition="2" size="165,30" font="Regular;24" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
        </screen>'''
    else:
        skin = '''<screen position="center,center" size="1886,1051" title="Command execution..." backgroundColor="#ff0a0510" flags="wfNoBorder">
            <eLabel position="0,0" size="1886,1051" backgroundColor="#0a0510" zPosition="-10"/>
            <eLabel position="0,0" size="1886,2" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,1049" size="1886,2" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="0,0" size="2,1051" backgroundColor="#bf5fff" zPosition="2"/>
            <eLabel position="1884,0" size="2,1051" backgroundColor="#bf5fff" zPosition="2"/>
            <widget name="text" position="9,93" size="1868,897" backgroundColor="#0e0518" foregroundColor="#e0d0f0" font="Console;33"/>
            <eLabel text="Command execution..." font="Regular;45" size="1163,80" position="8,3" foregroundColor="#f0e0ff" backgroundColor="#0a0510" zPosition="4"/>
            <eLabel position="10,1043" size="250,5" backgroundColor="#c0392b" zPosition="1"/>
            <eLabel position="353,1043" size="250,5" backgroundColor="#9970bb" zPosition="1"/>
            <eLabel position="1626,1043" size="250,5" backgroundColor="#27ae60" zPosition="1"/>
            <eLabel text="Cancel" position="10,1004" zPosition="2" size="250,40" font="Regular;28" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel text="Hide/Show" render="Label" position="353,1004" zPosition="2" size="250,40" font="Regular;28" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
            <eLabel text="Restart GUI" position="1626,1004" zPosition="2" size="250,40" font="Regular;28" halign="center" valign="center" backgroundColor="#0a0510" foregroundColor="#f0e0ff" transparent="1"/>
        </screen>'''

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
        if skin:
            self.skinName = [skin, 'Console']
        self.errorOcurred = False
        self['text'] = ScrollLabel('')
        self['key_red'] = Label(_('Cancel'))
        self['key_green'] = Label(_('Hide/Show'))
        self['key_blue'] = Label(_('Restart'))
        self["actions"] = ActionMap(
            ["WizardActions", "DirectionActions", 'ColorActions'],
            {
                "ok": self.cancel,
                "up": self["text"].pageUp,
                "down": self["text"].pageDown,
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

    def updateTitle(self):
        self.setTitle(self.newtitle)

    def startRun(self):
        if self.showStartStopText:
            self['text'].setText(_('Execution progress\n\n'))
        print('[Console] executing in run', self.run,
              ' the command:', self.cmdlist[self.run])
        print("[Console] Executing command:", self.cmdlist[self.run])
        if self.container.execute(self.cmdlist[self.run]):
            self['text'].setText(self.cmdlist[self.run])
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
            self['text'].appendText('Execution finished!!')

        if self.finishedCallback:
            self.finishedCallback()

        if self.errorOcurred or not self.closeOnSuccess:
            self['text'].appendText('\nPress OK or Exit to abort!')
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
        self['text'].appendText(data)

    def restartenigma(self):
        from Screens.Standby import TryQuitMainloop
        self.session.open(TryQuitMainloop, 3)
