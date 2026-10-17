import { Board } from '@/scenes/games/gomoku/Board';
import { gomokuPresentation } from '@/scenes/games/gomoku/presentation';

const gameScenes = { gomoku: { ...gomokuPresentation, Board } };

export function gameSceneFor(gameType: string) {
  return Object.entries(gameScenes).find(([type]) => type === gameType)?.[1];
}
