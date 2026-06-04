import { NextResponse } from "next/server";

export const AUTH_COOKIE_NAME = "rivalens_access_token";

export function backendAuthUrl(path: string) {
  const backendUrl =
    process.env.NEXT_PUBLIC_RIVALENS_API_URL || "http://localhost:8000";
  return `${backendUrl}${path}`;
}

export function setAuthCookie(
  response: NextResponse,
  accessToken: string,
  expiresIn: number,
) {
  response.cookies.set(AUTH_COOKIE_NAME, accessToken, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: expiresIn,
  });
}

export function clearAuthCookie(response: NextResponse) {
  response.cookies.set(AUTH_COOKIE_NAME, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}
