import { api } from "./api.js";

const b64 = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=")), (c) => c.charCodeAt(0));

const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const standalone = () => window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

/** What can this device do right now? iPhones only allow web push once FINN is added to the Home Screen. */
export async function pushStatus() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return { state: isIOS() && !standalone() ? "needs-install" : "unsupported" };
  }
  const key = await api.pushKey().catch(() => null);
  if (!key?.enabled) return { state: "unavailable" };
  if (Notification.permission === "denied") return { state: "denied" };
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  return { state: sub ? "on" : "off", key: key.publicKey };
}

export async function enablePush(publicKey) {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications were blocked for this site. You can allow them in the browser's site settings.");
  const reg = await navigator.serviceWorker.ready;
  let sub;
  try {
    sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(publicKey) });
  } catch (e) {
    throw new Error("This browser couldn't register for push notifications (" + (e.message || e.name) + "). Chrome on Android and an installed Home Screen app on iPhone support it.");
  }
  await api.pushSubscribe(sub.toJSON());
}

export async function disablePush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    await api.pushUnsubscribe(sub.toJSON()).catch(() => {});
    await sub.unsubscribe();
  }
}
