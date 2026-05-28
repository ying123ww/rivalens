import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const backendUrl = process.env.NEXT_PUBLIC_RIVALENS_API_URL || 'http://localhost:8000';

  try {
    const body = await request.json();
    const response = await fetch(`${backendUrl}/api/industry-directions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('POST /api/industry-directions - Error proxying to backend:', error);
    return NextResponse.json(
      { error: 'Failed to connect to backend service' },
      { status: 500 }
    );
  }
}
