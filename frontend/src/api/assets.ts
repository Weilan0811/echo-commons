import { apiBaseUrl, request, type SchemaOf } from './http';

export type ImageAsset = SchemaOf<'AssetView'>;
export type ImageGeneration = SchemaOf<'GenerationView'>;
export function imageUrl(url: string): string {
  return url.startsWith('/api/') ? new URL(url, apiBaseUrl()).href : url;
}
export function assetImage(asset: ImageAsset): string {
  return imageUrl(asset.images.find((image) => image.variant === 'standard')!.url);
}
export const imageAssets = {
  styles: () => request<SchemaOf<'StyleView'>[]>('/api/assets/generation-styles'),
  list: (playerId: string, cursor: string | null) => request<SchemaOf<'Page_AssetView_'>>('/api/assets', {
    query: { player_id: playerId, purpose: 'character_illustration', cursor, limit: 50 },
  }),
  get: (playerId: string, assetId: string) => request<ImageAsset>(`/api/assets/${assetId}`, { query: { player_id: playerId } }),
  generate: (body: SchemaOf<'GenerationRequest'>) => request<ImageGeneration>('/api/image-generations', { method: 'POST', body }),
  generation: (playerId: string, id: string) => request<ImageGeneration>(`/api/image-generations/${id}`, { query: { player_id: playerId } }),
  crop: (assetId: string, body: SchemaOf<'CropRequest'>) => request<ImageAsset>(`/api/assets/${assetId}/avatar-crops`, { method: 'POST', body }),
};
