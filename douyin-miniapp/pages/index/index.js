const customerService = require("../../config/customer-service");

Page({
  data: {
    imId: customerService.supervisorDouyinId,
    serviceReady: Boolean(customerService.supervisorDouyinId),
  },

  imCallback(event) {
    console.log("跳转抖音 IM 客服成功", event && event.detail);
    tt.showToast({
      title: "正在打开客服会话",
      icon: "success",
      duration: 1800,
    });
  },

  onImError(event) {
    const detail = (event && event.detail) || {};
    const message = detail.errMsg || "请确认客服主管抖音号已正确绑定";

    console.error("拉起抖音 IM 客服失败", detail);
    tt.showModal({
      title: "暂时无法打开客服",
      content: message,
      showCancel: false,
      confirmText: "我知道了",
    });
  },
});
