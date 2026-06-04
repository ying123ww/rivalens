import { NextResponse } from "next/server";

import { backendAuthUrl, setAuthCookie } from "../_shared";

export async function POST(request: Request) {
  try {
    const response = await fetch(backendAuthUrl("/api/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(await request.json()),
      cache: "no-store",
    });
    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    const nextResponse = NextResponse.json(
      { user: data.user },
      { status: response.status },
    );
    setAuthCookie(nextResponse, data.access_token, data.expires_in);
    return nextResponse;
  } catch (error) {
    console.error("POST /api/auth/register - Backend connection failed:", error);
    return NextResponse.json(
      { detail: "无法连接认证服务" },
      { status: 503 },
    );
  }
}
