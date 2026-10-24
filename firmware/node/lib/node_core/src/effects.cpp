#include "effects.h"

using proto::Effect;

Rgb scale(Rgb c, uint8_t level) {
  return Rgb{static_cast<uint8_t>((c.r * level + 127) / 255), static_cast<uint8_t>((c.g * level + 127) / 255),
             static_cast<uint8_t>((c.b * level + 127) / 255)};
}

bool EffectPlayer::apply(const proto::Led& cmd, uint32_t now) {
  if (cmd.effect_id != 0 && cmd.effect_id == cmd_.effect_id && cmd.effect == cmd_.effect) {
    return false;  // re-send (the hub repeats lit targets every 2 s)
  }
  if (cmd.effect_id != 0 && cmd.effect_id == consumed_id_ && cmd.effect != static_cast<uint8_t>(Effect::Off)) {
    return false;  // stale re-send of a target that was already hit
  }
  cmd_ = cmd;
  start_ = now;
  lit_at_ = effect() == Effect::Off ? 0 : now;
  return true;
}

void EffectPlayer::clear(uint32_t now) {
  consumed_id_ = cmd_.effect_id;  // a late re-send of it must not relight the target
  cmd_ = proto::Led{};
  start_ = now;
  lit_at_ = 0;
}

bool EffectPlayer::lit(uint32_t now) const {
  const uint32_t t = now - start_;
  switch (effect()) {
    case Effect::Off:
      return false;
    case Effect::Blink:
      return !cmd_.p2 || t / (cmd_.p1 ? cmd_.p1 : 500) < cmd_.p2;
    case Effect::Flash:
      return t < (cmd_.p1 ? cmd_.p1 : 100);
    default:
      return true;
  }
}

Rgb EffectPlayer::render(uint32_t now) const {
  const Rgb color{cmd_.r, cmd_.g, cmd_.b};
  const uint32_t t = now - start_;
  switch (effect()) {
    case Effect::Off:
      return Rgb{0, 0, 0};
    case Effect::Solid:
      return color;
    case Effect::Blink: {
      uint32_t period = cmd_.p1 ? cmd_.p1 : 500;
      if (cmd_.p2 && t / period >= cmd_.p2) return Rgb{0, 0, 0};
      return (t % period) < period / 2 ? color : Rgb{0, 0, 0};
    }
    case Effect::Pulse: {
      uint32_t period = cmd_.p1 ? cmd_.p1 : 1000;
      // triangle 0..255..0, squared for a softer "breathe"
      uint32_t phase = (t % period) * 510 / period;
      uint32_t tri = phase <= 255 ? phase : 510 - phase;
      return scale(color, static_cast<uint8_t>(tri * tri / 255));
    }
    case Effect::Flash:
      return t < (cmd_.p1 ? cmd_.p1 : 100) ? color : Rgb{0, 0, 0};
    case Effect::Ramp: {
      uint32_t dur = cmd_.p1 ? cmd_.p1 : 1;
      uint32_t from = cmd_.p2;
      uint32_t level = t >= dur ? 255 : from + (255 - from) * t / dur;
      return scale(color, static_cast<uint8_t>(level));
    }
  }
  return Rgb{0, 0, 0};
}
