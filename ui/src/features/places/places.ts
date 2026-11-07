/** A town with photos, from /api/places: named on this PC from the photos' GPS positions. */
export type PlaceRow = {
  id: number;
  name: string;
  admin1: string | null;
  country: string;
  cc: string;
  lat: number;
  lon: number;
  n: number;
  first: number | null;
  last: number | null;
  cover: number | null;
  cover_v: number | null;
};
export type PlacesResult = { places: PlaceRow[]; located: number; with_gps: number };

/** "Calangute, Goa, India"; a state named like its town (Goa, Goa) only once. */
export const placeName = (p: Pick<PlaceRow, 'name' | 'admin1' | 'country'>) =>
  [p.name, p.admin1 !== p.name ? p.admin1 : null, p.country].filter(Boolean).join(', ');
