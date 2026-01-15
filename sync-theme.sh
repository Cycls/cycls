#!/bin/bash
curl -L https://github.com/Cycls/agentUI/releases/download/latest/agentUI.zip -o /tmp/agentUI.zip
rm -rf cycls/themes/default/*
unzip /tmp/agentUI.zip -d cycls/themes/default/
rm /tmp/agentUI.zip
