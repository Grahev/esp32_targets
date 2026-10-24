#include "hit_filter.h"

void HitFilter::configure(uint16_t debounce_ms, uint8_t edges, uint16_t window_ms) {
  debounce_ms_ = debounce_ms;
  need_ = edges ? edges : 1;
  window_ms_ = window_ms;
  count_ = 0;
}

HitResult HitFilter::onEdge(uint32_t ms) {
  if (locked_ && static_cast<int32_t>(ms - lock_from_) < debounce_ms_) {
    return HitResult{false, 0, 0};
  }
  locked_ = false;
  if (count_ == 0 || ms - first_ > window_ms_) {
    first_ = ms;
    count_ = 0;
  }
  count_++;
  if (count_ < need_) return HitResult{false, 0, count_};
  HitResult r{true, first_, count_};
  locked_ = true;
  lock_from_ = first_;
  count_ = 0;
  return r;
}

void HitFilter::poll(uint32_t now) {
  if (count_ && now - first_ > window_ms_) count_ = 0;
}
