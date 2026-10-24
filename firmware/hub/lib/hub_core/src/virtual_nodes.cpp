#include "virtual_nodes.h"

#include "version.h"

namespace {
const NodeInfo INFO{TARGETS_FW_MAJOR, TARGETS_FW_MINOR, TARGETS_FW_PATCH, 0, proto::CAP_EFFECTS | proto::CAP_NODE_RT};
}

bool VirtualNodes::VIo::send(const uint8_t* to, const uint8_t* data, size_t len) {
  (void)to;  // everything a virtual node sends goes to the hub
  OutFrame f;
  f.from = mac;
  f.len = static_cast<uint8_t>(len);
  memcpy(f.data, data, len);
  owner->outbox_.push_back(f);
  done_pending = true;
  return true;
}

void VirtualNodes::resize(uint8_t count, uint32_t now) {
  while (nodes_.size() > count) nodes_.pop_back();
  while (nodes_.size() < count) {
    auto v = std::unique_ptr<VNode>(new VNode());
    v->mac = Mac::virtualNode(static_cast<uint8_t>(nodes_.size() + 1));
    v->io.owner = this;
    v->io.mac = v->mac;
    v->logic.reset(new NodeLogic(v->io, v->cfg, INFO));
    v->logic->setBattery(3950, 75, 0);
    v->logic->begin(now);
    nodes_.push_back(std::move(v));
  }
}

void VirtualNodes::deliver(const Mac* mac, const uint8_t* data, size_t len) {
  for (auto& v : nodes_) {
    if (!mac || v->mac == *mac) v->inbox.emplace_back(data, data + len);
  }
}

void VirtualNodes::hit(const Mac& mac, uint32_t now) {
  for (auto& v : nodes_)
    if (v->mac == mac) v->logic->onEdge(now);
}

uint32_t VirtualNodes::rnd(uint32_t n) {
  rng_ ^= rng_ << 13;
  rng_ ^= rng_ >> 17;
  rng_ ^= rng_ << 5;
  return n ? rng_ % n : 0;
}

void VirtualNodes::tick(uint32_t now, bool autoshoot, uint8_t expected) {
  static const uint8_t HUB_MAC[6] = {0};  // virtual nodes don't check the sender beyond the first Welcome
  for (auto& v : nodes_) {
    NodeLogic& n = *v->logic;
    for (auto& f : v->inbox) {
      // Frames from the hub: use the hub's identity the node learned, or a fixed one
      n.onFrame(v->cfg.has_hub ? v->cfg.hub_mac : HUB_MAC, f.data(), f.size(), now);
    }
    v->inbox.clear();
    if (v->io.done_pending) {
      v->io.done_pending = false;
      n.onSendDone(true, now);
    }
    n.tick(now);

    if (!autoshoot) {
      v->shot_scheduled = false;
      continue;
    }
    Rgb c = n.led(now);
    bool red = c.r > 30 && c.g < c.r / 3 && c.b < c.r / 3 && n.mode() == proto::Mode::Active;
    bool wanted = red || (expected && expected == v->cfg.node_id && n.mode() == proto::Mode::Active);
    if (static_cast<int32_t>(now - v->cooldown_until) < 0) continue;
    if (wanted && !v->shot_scheduled) {
      v->shot_scheduled = true;
      v->shoot_at = now + 450 + rnd(650);  // 0.45-1.1 s, like a decent shooter
    } else if (!wanted) {
      v->shot_scheduled = false;
    }
    if (v->shot_scheduled && static_cast<int32_t>(now - v->shoot_at) >= 0) {
      n.onEdge(now);
      v->shot_scheduled = false;
      v->cooldown_until = now + 400;  // let the hub process it before aiming again
    }
  }
}
