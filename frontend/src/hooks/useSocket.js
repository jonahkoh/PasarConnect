import { useEffect, useState } from "react";
import { io } from "socket.io-client";

/**
 * Decodes the `exp` claim from a JWT without verifying.
 * Returns Unix timestamp in seconds, or null on failure.
 */
function decodeJwtExp(token) {
  try {
    return JSON.parse(atob(token.split(".")[1])).exp ?? null;
  } catch {
    return null;
  }
}

/**
 * Connects to the Socket.io notification service via the Vite → Kong proxy.
 * Authenticates using the RS256 JWT from authUser.token.
 *
 * Returns the live socket instance (null before connect / after disconnect).
 *
 * Behaviour:
 * - Disconnects and clears session 30 s before JWT expiry, then redirects to /login.
 * - On connect_error with "expired"/"authentication failed" does the same.
 * - Disconnects cleanly on component unmount.
 */
export function useSocket(authUser) {
  const [socket, setSocket] = useState(null);

  useEffect(() => {
    if (!authUser?.token) return;

    const s = io("", {
      path: "/socket.io",
      auth: { token: authUser.token },
      transports: ["polling", "websocket"],
    });
    setSocket(s);

    // Schedule disconnect 30 s before the JWT's exp claim
    const exp = decodeJwtExp(authUser.token);
    let expiryTimer = null;
    if (exp) {
      const delay = exp * 1000 - Date.now() - 30_000;
      if (delay > 0) {
        expiryTimer = setTimeout(() => {
          s.disconnect();
          sessionStorage.clear();
          window.location.replace("/login");
        }, delay);
      }
    }

    s.on("connect_error", (err) => {
      const msg = err.message.toLowerCase();
      if (msg.includes("expired") || msg.includes("authentication failed")) {
        s.disconnect();
        sessionStorage.clear();
        window.location.replace("/login");
      }
    });

    return () => {
      clearTimeout(expiryTimer);
      s.disconnect();
      setSocket(null);
    };
  }, [authUser?.token]);

  return socket;
}
