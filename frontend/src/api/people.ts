import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from './http';
import { newUuid } from '@/lib/clientMessageId';

export type Person = SchemaOf<'PersonView'>;

export function usePeople(playerId: string) {
  return useQuery({
    queryKey: ['character-people', playerId],
    queryFn: () => request<Person[]>('/api/character-people', { query: { player_id: playerId } }),
    enabled: playerId !== '',
  });
}

export function useRegisterPerson(playerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description: string }) => request<Person>('/api/character-people', {
      method: 'POST',
      body: { player_id: playerId, person_id: newUuid(), display_name: input.name, description: input.description },
    }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['character-people', playerId] }),
  });
}

export function usePersonBindings(playerId: string, communityId: string | null) {
  return useQuery({
    queryKey: ['person-bindings', communityId, playerId],
    queryFn: () => request<{ person_id: string; actor_kind: 'player' | 'character'; actor_id: string }[]>(`/api/communities/${encodeURIComponent(communityId ?? '')}/person-bindings`, { query: { player_id: playerId } }),
    enabled: communityId !== null && playerId !== '',
  });
}

export function useBindPerson(playerId: string, communityId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { personId: string; actorKind: 'player' | 'character'; actorId: string }) => request(`/api/communities/${encodeURIComponent(communityId ?? '')}/person-bindings`, {
      method: 'PUT', body: { player_id: playerId, person_id: input.personId, actor_kind: input.actorKind, actor_id: input.actorId },
    }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['person-bindings', communityId, playerId] });
      await client.invalidateQueries({ queryKey: ['character-people', playerId] });
    },
  });
}
