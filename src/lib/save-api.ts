/**
 * API client for the Python save parser service.
 * All requests go through the gateway using XTransformPort.
 */

const SERVICE_PORT = 3001;

function baseUrl(path: string): string {
  return `/${path}?XTransformPort=${SERVICE_PORT}`;
}

export interface SaveMeta {
  version: string;
  name: string;
  date: string;
  ironman: boolean;
  dlcs: string[];
  meta_fleets: number;
  meta_planets: number;
}

export interface ResourceInfo {
  value: number;
  label: string;
  icon: string;
  income: number;
}

export interface ResourceCategory {
  [category: string]: string[];
}

export interface CountryInfo {
  id: string;
  name: string;
  type: string;
  custom_name: boolean;
  capital: number | string;
  military_power: number;
  economy_power: number;
  tech_power: number;
  fleet_size: number;
}

export interface SpeciesInfo {
  id: string;
  name: string;
  class: string;
  portrait: string;
  traits: string[];
  home_planet: number | string;
}

export interface GameStats {
  date: string;
  tick: number;
  num_species: number;
  num_countries: number;
  player_country_id: string;
  tech_count: number;
  fleet_size: number;
  military_power: number;
  empire_size: number;
  owned_planets_count: number;
}

export interface UploadResponse {
  success: boolean;
  filename: string;
  meta: SaveMeta;
  player_country_id: string;
  gamestate_size: number;
  split_info?: Record<string, number>;
}

export interface ResourcesResponse {
  resources: Record<string, ResourceInfo>;
  country_id: string;
  categories: ResourceCategory;
}

export interface CountriesResponse {
  countries: CountryInfo[];
  player_country_id: string;
}

export interface SpeciesResponse {
  species: SpeciesInfo[];
  total: number;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `Request failed: ${res.status}`);
  }
  // For file downloads
  if (res.headers.get('content-type')?.includes('application/zip')) {
    return res as unknown as T;
  }
  return res.json();
}

export async function uploadSave(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return request<UploadResponse>(baseUrl('api/upload'), {
    method: 'POST',
    body: file,
  });
}

export async function getStatus() {
  return request<{ loaded: boolean; filename: string | null }>(baseUrl('api/status'));
}

export async function getMeta() {
  return request<SaveMeta>(baseUrl('api/meta'));
}

export async function getStats() {
  return request<GameStats>(baseUrl('api/stats'));
}

export async function getResources(countryId: string) {
  return request<ResourcesResponse>(baseUrl(`api/resources?country_id=${countryId}`));
}

export async function getCountries() {
  return request<CountriesResponse>(baseUrl('api/countries'));
}

export async function getSpecies() {
  return request<SpeciesResponse>(baseUrl('api/species'));
}

export async function updateResources(countryId: string, resources: Record<string, number>) {
  return request<{ success: boolean; message: string }>(baseUrl('api/resources'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ country_id: countryId, resources }),
  });
}

export async function updateDate(date: string) {
  return request<{ success: boolean; date: string }>(baseUrl('api/date'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date }),
  });
}

export async function updateName(name: string) {
  return request<{ success: boolean; name: string }>(baseUrl('api/name'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function exportSave(): Promise<Blob> {
  const res = await fetch(baseUrl('api/export'), {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Export failed');
  return res.blob();
}

export async function releaseSave() {
  return request<{ success: boolean }>(baseUrl('api/save'), { method: 'DELETE' });
}

// ===== New APIs: Events & Flag =====

export interface DelayedEvent {
  index: number;
  event: string;
  days: number;
  scope_type: string;
  scope_id: string;
}

export interface FlagInfo {
  icon_category: string;
  icon_file: string;
  bg_category: string;
  bg_file: string;
  colors: string[];
}

export interface FlagCategoryInfo {
  label: string;
  prefix: string;
  count: number;
  dlc: string;
}

export interface EventsResponse {
  events: DelayedEvent[];
  country_id: string;
}

export interface FlagResponse {
  flag: FlagInfo;
  country_id: string;
  available_categories: Record<string, FlagCategoryInfo>;
  available_backgrounds: string[];
  available_colors: string[];
}

export async function getEvents(countryId: string) {
  return request<EventsResponse>(baseUrl(`api/events?country_id=${countryId}`));
}

export async function getFlag(countryId: string) {
  return request<FlagResponse>(baseUrl(`api/flag?country_id=${countryId}`));
}

export async function updateEvents(countryId: string, events: { index: number; days: number }[]) {
  return request<{ success: boolean; message: string }>(baseUrl('api/events'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ country_id: countryId, events }),
  });
}

export async function updateFlag(countryId: string, flag: FlagInfo) {
  return request<{ success: boolean; message: string }>(baseUrl('api/flag'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ country_id: countryId, flag }),
  });
}