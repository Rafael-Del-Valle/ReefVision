(module
  ;; Return mean green intensity as a fraction of the 8-bit channel range.
  (func (export "measure")
    (param $red f64) (param $green f64) (param $blue f64) (param $pixels i64)
    (result f64)
    local.get $green
    f64.const 255
    f64.div))
