# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import

import sys
from Components.Label import Label
from Screens.Screen import Screen
from enigma import eTimer
from threading import Lock
from twisted.internet import reactor

"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin - Notification System       #
#  Created by Lululla                                   #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0/   #
#  Last Modified: 20260317                              #
#                                                       #
#  Features:                                            #
#    - Thread-safe singleton notification manager       #
#    - Python 2/3 compatible                            #
#    - Message queue for pre-initialization messages    #
#    - Download status notifications                    #
#                                                       #
#########################################################
"""

__author__ = "Lululla"

if sys.version_info[0] >= 3:
    unicode = str


class SimpleNotifyWidget(Screen):
    """Simple notification widget for Enigma2 plugins"""

    skin = """
    <screen position="360,15" size="1200,50" flags="wfNoBorder" backgroundColor="#ff6699">
        <eLabel position="0,0" size="1200,4" backgroundColor="#ffff00" />
        <eLabel position="0,46" size="1200,4" backgroundColor="#ffff00" />
        <eLabel position="0,5" size="1200,40" backgroundColor="#cc3399" />
        <eLabel position="9,7" size="1180,34" backgroundColor="#00142030" halign="center" />
        <widget name="notification_text" position="9,7" size="1180,34" font="Regular;32" foregroundColor="#00FFFFFF" backgroundColor="#ff6699" halign="center" valign="center" zPosition="4" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        try:
            self.skin = SimpleNotifyWidget.skin
        except BaseException:
            self.__dict__['skin'] = SimpleNotifyWidget.skin
        self["notification_text"] = Label("")
        self.onLayoutFinish.append(self._setupUI)

    def _setupUI(self):
        """Setup UI after layout completion"""
        try:
            if hasattr(self.instance, 'setAnimationMode'):
                self.instance.setAnimationMode(0)
        except Exception:
            pass

    def updateMessage(self, text):
        """Update notification text"""
        if sys.version_info[0] < 3 and isinstance(text, unicode):
            self["notification_text"].setText(text.encode('utf-8'))
        else:
            self["notification_text"].setText(text)


class HybridNotificationManager:
    """Singleton notification manager - works globally across all threads"""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(
                    HybridNotificationManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.notification_window = None
        self.session = None
        self.hide_timer = eTimer()
        try:
            self.hide_timer.callback.append(self._hideNotification)
        except AttributeError:
            self.hide_timer_conn = self.hide_timer.timeout.connect(
                self._hideNotification)
        self.pending_messages = []  # Queue for messages waiting
        self.pending_timer = eTimer()
        try:
            self.pending_timer.callback.append(self._processPendingMessages)
        except AttributeError:
            self.pending_timer.timeout.connect(self._processPendingMessages)

    def initialize(self, session):
        """Initialize manager with session"""
        self.session = session
        if not self.notification_window and session:
            try:
                self.notification_window = session.instantiateDialog(
                    SimpleNotifyWidget)
                print("[NOTIFY] Notification window created")
            except Exception as e:
                print("[NOTIFY] Error creating window: {}".format(e))

        # Process any pending messages
        if self.pending_messages:
            self.pending_timer.start(100, True)

    def _hideNotification(self):
        """Hide notification (timer callback)"""
        if self.notification_window:
            self.notification_window.hide()

    def _processPendingMessages(self):
        """Process pending messages after initialization"""
        if self.pending_messages and self.notification_window:
            for msg, duration in self.pending_messages:
                self._showMessage(msg, duration)
            self.pending_messages = []

    def _showMessage(self, message, duration):
        """Internal method to show message"""
        try:
            if self.notification_window and self.session:
                self.hide_timer.stop()

                # Convert message to correct format
                if sys.version_info[0] < 3 and isinstance(message, unicode):
                    display_msg = message.encode('utf-8')
                else:
                    display_msg = str(message)

                self.notification_window.updateMessage(display_msg)
                self.notification_window.show()
                self.hide_timer.start(duration, True)

                # Log for debug
                print("[NOTIFY] {} ({}ms)".format(display_msg, duration))
                return True
            return False
        except Exception as e:
            print("[NOTIFY] Error showing message: {}".format(e))
            return False

    def showMessage(self, message, duration=3000):
        """Show a notification message.

        Safe to call from any thread, including background threads -
        the actual widget/timer updates in _showMessage() are Enigma2
        GUI operations, which aren't safe to touch off the reactor
        thread, so marshal onto it via reactor.callFromThread() rather
        than calling _showMessage() directly.
        """
        # If not initialized yet, queue the message
        if not self.notification_window or not self.session:
            self.pending_messages.append((message, duration))
            if len(self.pending_messages) > 10:  # Limit queue size
                self.pending_messages = self.pending_messages[-10:]
            return

        reactor.callFromThread(self._showMessage, message, duration)

    def show_download_status(self, title, status, file_size=0):
        """Display a download status notification"""
        icons = {
            'completed': u'✅',
            'error': u'❌',
            'downloading': u'🚀',
            'paused': u'⏸️',
            'queued': u'📥'
        }

        icon = icons.get(status, u'ℹ️')

        if status == 'completed' and file_size > 0:
            size_mb = float(file_size) / (1024.0 * 1024.0)
            message = u"{} {}\nCompleted - {:.1f}MB".format(
                icon, title, size_mb)
        elif status == 'downloading':
            message = u"{} Downloading\n{}".format(icon, title)
        elif status == 'error':
            message = u"{} Download error\n{}".format(icon, title)
        elif status == 'paused':
            message = u"{} Download paused\n{}".format(icon, title)
        else:
            message = u"{} {}".format(icon, title)

        self.showMessage(message, 5000)

    def show(self, message, seconds=3):
        """Simplified version with duration in seconds"""
        self.showMessage(message, seconds * 1000)

    def hide(self):
        """Hide notification immediately. Safe to call from any thread -
        see showMessage()."""
        reactor.callFromThread(self._hideNow)

    def _hideNow(self):
        self.hide_timer.stop()
        self._hideNotification()


# Global singleton instance
_notification_manager = HybridNotificationManager()


# Public API functions
def init_notification_system(session):
    """
    Initialize notification system (call this ONCE at plugin startup)

    Args:
        session: Enigma2 session object
    """
    _notification_manager.initialize(session)
    # Show any pending messages immediately
    _notification_manager._processPendingMessages()


def show_notification(message, duration=3000):
    """
    Show a notification message (thread-safe)

    Args:
        message (str): Text to display
        duration (int): Display duration in milliseconds (default: 3000)
    """
    _notification_manager.showMessage(message, duration)


def show_download_notification(title, status, file_size=0):
    """Show download-specific notification"""
    _notification_manager.show_download_status(title, status, file_size)


def quick_notify(message, seconds=3):
    """
    Quick notification with duration in seconds

    Args:
        message (str): Text to display
        seconds (int): Display duration in seconds (default: 3)
    """
    _notification_manager.show(message, seconds)


def hide_current_notification():
    """Hide the current notification immediately"""
    _notification_manager.hide()


def cleanup_notifications():
    """Clean up notifications when plugin closes"""
    _notification_manager.hide()
    print("[NOTIFY] Cleanup complete")


# =============================================================================
# USAGE EXAMPLES - How to use in your plugins
# =============================================================================

"""
from .notification_system import init_notification_system, quick_notify, show_notification

# 1. INITIALIZATION (in your main plugin class)
class MyPlugin(Screen):
    def __init__(self, session):
        Screen.__init__(self, session)
        # Initialize notification system once
        init_notification_system(session)

# 2. BASIC USAGE
# Show 3-second notification
show_notification("Processing completed!")

# Show 5-second notification
show_notification("Download finished", 5000)

# Simplified version (seconds instead of milliseconds)
quick_notify("File saved successfully")

# Longer notification
quick_notify("Backup completed successfully", 5)

# Hide manually if needed
hide_current_notification()

# 3. AFTER OPERATIONS
def on_download_finished(self, success, filename):
    if success:
        quick_notify("Downloaded: {0}".format(filename))
    else:
        quick_notify("Download failed!", 5)

def on_processing_done(self, result):
    quick_notify("Processed {0} files".format(result.file_count))

# 4. ERROR NOTIFICATIONS
def handle_error(self, error_message):
    quick_notify("Error: {0}".format(error_message), 5)
"""
