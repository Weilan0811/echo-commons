import type { SchemaOf } from '@/api/http';

type Character = SchemaOf<'CharacterView'>;

export function canCharacterChat(character: Character): boolean {
  return character.availability_status === 'available' && character.memory_status === 'ready';
}

export function characterStatusText(character: Character): string {
  if (character.memory_status === 'preparing') return '记忆准备中';
  if (character.memory_status === 'failed') return '记忆准备失败';
  return canCharacterChat(character) ? '可参与对话' : '暂不可用';
}

export function characterPreparationError(_character: Character): string {
  return '记忆准备未完成，已保存的人物资料仍然保留，可以重新准备。';
}
