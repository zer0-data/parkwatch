import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const upstream = new URL(`/api/${path.join("/")}`, BACKEND_URL);
  upstream.search = request.nextUrl.search;

  try {
    const response = await fetch(upstream, {
      headers: { accept: "application/json" },
      cache: "no-store"
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json"
      }
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "ParkWatch backend is unavailable. Start FastAPI with `python -m uvicorn backend.app.main:app --reload`."
      },
      { status: 503 }
    );
  }
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const upstream = new URL(`/api/${path.join("/")}`, BACKEND_URL);
  upstream.search = request.nextUrl.search;

  try {
    const response = await fetch(upstream, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json"
      },
      body: await request.text(),
      cache: "no-store"
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json"
      }
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "ParkWatch backend is unavailable. Start FastAPI with `python -m uvicorn backend.app.main:app --reload`."
      },
      { status: 503 }
    );
  }
}
