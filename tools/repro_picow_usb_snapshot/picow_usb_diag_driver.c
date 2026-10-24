/* Temporary passive diagnostic accessor. Caller holds the IRQ lock. */
size_t envhub_udc_snapshot(uint32_t *out, size_t capacity)
{
    const struct device *dev = DEVICE_DT_INST_GET(0);
    const struct rpi_pico_config *config = dev->config;
    struct rpi_pico_data *priv = udc_get_private(dev);
    struct udc_data *data = dev->data;
    usb_hw_t *base = config->base;
    size_t n = 0;
    if (capacity < 56) {
        return 0;
    }
    out[n++] = 1;
    out[n++] = k_uptime_get_32();
    out[n++] = (uintptr_t)&priv->thread_data;
    out[n++] = (uintptr_t)&data->mutex;
    out[n++] = (uintptr_t)data->mutex.owner;
    out[n++] = data->mutex.lock_count;
    out[n++] = priv->events.events;
    out[n++] = atomic_get(&priv->xfer_new);
    out[n++] = atomic_get(&priv->xfer_finished);
    out[n++] = base->sof_rd;
    out[n++] = base->sie_status;
    out[n++] = base->buf_status;
    out[n++] = base->ints;
    out[n++] = base->abort;
    out[n++] = base->abort_done;
    out[n++] = base->dev_addr_ctrl;
    for (uint8_t idx = 0; idx < 4; idx++) {
        for (uint8_t direction = 0; direction < 2; direction++) {
            uint8_t ep = idx | (direction ? USB_EP_DIR_IN : USB_EP_DIR_OUT);
            struct udc_ep_config *cfg = udc_get_ep_cfg(dev, ep);
            struct net_buf *buf = udc_buf_peek(cfg);
            out[n++] = ep;
            out[n++] = read_buf_ctrl_reg(dev, ep);
            out[n++] = udc_ep_is_busy(cfg) | (cfg->stat.halted << 1);
            out[n++] = (uintptr_t)buf;
            out[n++] = buf ? buf->len : 0;
        }
    }
    return n;
}
