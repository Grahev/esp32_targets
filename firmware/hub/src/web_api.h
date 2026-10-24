#pragma once

#include <ArduinoJson.h>
#include <ESPAsyncWebServer.h>

#include "hub.h"

// Things the web layer asks main.cpp to do
class WebActions {
 public:
  virtual ~WebActions() {}
  virtual void rebootIn(uint32_t ms) = 0;
  virtual void factoryReset() = 0;
  virtual void diag(JsonObject o) = 0;
};

void setupWeb(AsyncWebServer& server, AsyncWebSocket& ws, Hub& hub, WebActions& actions);
