#!/bin/sh
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 20260122                              #
#                                                       #
#  Credits:                                             #
#  - Original concept by Lululla                        #
#  - Special thanks to @KiddaC for support              #
#  - Background images by @oktus                        #
#  - Additional contributions by Qu4k3                  #
#  - Linuxsat-support.com & Corvoboys communities       #
#                                                       #
#  Usage of this code without proper attribution        #
#  is strictly prohibited.                              #
#  For modifications and redistribution,                #
#  please maintain this credit header.                  #
#########################################################

echo "========================================"
echo "   STARTING VAVOO PROXY FOR ENIGMA2"
echo "========================================"
echo "Date: $(date)"
echo ""

# Stop any existing proxy
pkill -f "vavoo_proxy.py" 2>/dev/null
sleep 2

# Some images install plugins under /usr/lib64 instead of /usr/lib
if [ -d /usr/lib64/enigma2/python/Plugins/Extensions/vavoo ]; then
    PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/vavoo
else
    PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/vavoo
fi

# Start the proxy
cd "$PLUGINPATH"
python "$PLUGINPATH/start_proxy.py" > /tmp/vavoo_proxy.log 2>&1 &

# Wait a few seconds for startup
sleep 5

echo "Proxy started in background"
echo "Log: /tmp/vavoo_proxy.log"
echo "Check status: curl http://127.0.0.1:4323/status"
echo "========================================"

