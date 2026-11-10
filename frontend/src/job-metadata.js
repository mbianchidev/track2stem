export function jobMetadata(job) {
  const result = { ...job };
  if (job.analysis) {
    const { beats, downbeats, ...summary } = job.analysis;
    result.analysis = summary;
  }
  if (job.lyrics) {
    const { words, ...summary } = job.lyrics;
    result.lyrics = summary;
  }
  return result;
}
