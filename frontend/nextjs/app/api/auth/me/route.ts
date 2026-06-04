import { NextRequest, NextResponse } from "next/server";

import {
  AUTH_COOKIE_NAME,
  backendAuthUrl,
  clearAuthCookie,
} from "../_shared";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "需要登录" }, { status: 401 });
  }

  try {
    const response = await fetch(backendAuthUrl("/api/auth/me"), {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    const data = await response.json();
    const nextResponse = NextResponse.json(data, { status: response.status });

    if (response.status === 401) {
      clearAuthCookie(nextResponse);
    }
    return nextResponse;
  } catch (error) {
    console.error("GET /api/auth/me - Backend connection failed:", error);
    return NextResponse.json(
      { detail: "无法连接认证服务" },
      { status: 503 },
    );
  }
}
