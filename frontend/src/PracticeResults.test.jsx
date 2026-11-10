import React from 'react';
import { render, screen } from '@testing-library/react';
import PracticeResults from './PracticeResults.jsx';
import { jobMetadata } from './job-metadata.js';

test('meter changes and full-track tuning evidence remain visible with real artifact links', () => {
  const job = {
    id: 'synthetic-practice',
    analysis: {
      bpm: 120, meter_changes: [{ numerator: 3, denominator: 4 }, { numerator: 6, denominator: 8 }],
      tuning: { guitar: { candidate: 'Drop D', lowest_note: 'D2', analyzed_seconds: 120 } },
    },
    artifacts: { meter: '/owned/meter.csv' },
  };
  render(<PracticeResults job={job} apiBase="/api" />);
  expect(screen.getByText('3/4 to 6/8')).toBeInTheDocument();
  expect(screen.getByText('Analyzed 2:00 of audio')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Meter map (CSV)' })).toHaveAttribute('href', '/api/artifacts/synthetic-practice/meter');
});

test('undetermined meter is not shown as a fixed time signature', () => {
  render(<PracticeResults job={{ id: 'synthetic-unknown', analysis: { bpm: 120 } }} apiBase="/api" />);
  expect(screen.getByText('Undetermined')).toBeInTheDocument();
  expect(screen.getByText(/not forced to 4\/4/)).toBeInTheDocument();
});

test('history excludes both dense beat grids without changing the live analysis', () => {
  const job = { analysis: { bpm: 120, beats: [0, .5], downbeats: [0], meter_changes: [{ numerator: 3, denominator: 4 }] } };
  const saved = jobMetadata(job);
  expect(saved.analysis.beats).toBeUndefined();
  expect(saved.analysis.downbeats).toBeUndefined();
  expect(saved.analysis.meter_changes).toEqual(job.analysis.meter_changes);
  expect(job.analysis.beats).toEqual([0, .5]);
});
