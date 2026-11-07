import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { post } from '../lib/api';
import { PageError } from './ErrorScreens';

vi.mock('../lib/api', () => ({
  post: vi.fn(() => Promise.resolve({ ok: true })),
  get: vi.fn(() => Promise.resolve({ version: '9.9.9' })),
}));

function show(thrown: unknown) {
  function Broken(): never {
    throw thrown;
  }
  const router = createMemoryRouter(
    [
      { path: '/', element: <div>Home screen</div> },
      { errorElement: <PageError />, children: [{ path: '/places', element: <Broken /> }] },
    ],
    { initialEntries: ['/places'] },
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('a screen that fails', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined); // React reports the error too
    vi.mocked(post).mockClear();
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('says so in its place, keeps your data safe, and leads home', async () => {
    show(new Error('Cannot read properties of undefined'));
    expect(await screen.findByText('This screen ran into a problem')).toBeTruthy();
    expect(screen.getByText(/your photos, people and answers are safe/)).toBeTruthy();
    expect(screen.getByText(/Cannot read properties of undefined/)).toBeTruthy(); // in the details
    expect(vi.mocked(post)).toHaveBeenCalledWith('/api/diagnostics/ui-error', expect.objectContaining({ where: '/places' }));
    fireEvent.click(screen.getByText('Go to Home'));
    expect(await screen.findByText('Home screen')).toBeTruthy();
  });

  it('asks for a reload when an update left the old code behind', async () => {
    show(new TypeError('Failed to fetch dynamically imported module: app://ui/assets/Places-0ld.js'));
    expect(await screen.findByText('RecPro was updated')).toBeTruthy();
    expect(screen.getByText('Reload')).toBeTruthy();
    expect(screen.queryByText('Go to Home')).toBeNull();
  });
});
