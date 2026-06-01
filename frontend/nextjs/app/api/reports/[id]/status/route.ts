import { NextResponse } from 'next/server';

export async function GET(
  request: Request,
  { params }: { params: { id: string } }
) {
  const { id } = params;
  const backendUrl = process.env.NEXT_PUBLIC_RIVALENS_API_URL || 'http://localhost:8000';

  try {
    if (!id) {
      return NextResponse.json(
        { error: 'Missing report ID parameter' },
        { status: 400 }
      );
    }

    const response = await fetch(`${backendUrl}/api/reports/${id}/status`);
    const data = await response.json();

    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error(`GET /api/reports/${id}/status - Error proxying to backend:`, error);
    return NextResponse.json(
      { error: 'Failed to connect to backend service' },
      { status: 500 }
    );
  }
}
