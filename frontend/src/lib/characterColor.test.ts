import { describe, expect, it } from 'vitest';
import { accentColor, avatarColors, characterHue, splitForBubbles } from './characterColor';

describe('characterHue', () => {
  it('同一标识始终得到相同色相', () => {
    expect(characterHue('character-jin')).toBe(characterHue('character-jin'));
  });

  it('返回 0—359 的整数', () => {
    for (const id of ['a', 'character-1', 'character-2', 'preview-jin', 'x'.repeat(64)]) {
      const hue = characterHue(id);
      expect(Number.isInteger(hue)).toBe(true);
      expect(hue).toBeGreaterThanOrEqual(0);
      expect(hue).toBeLessThan(360);
    }
  });

  it('结构相近的标识不会落在相近色相', () => {
    // 直接对散列取模时这两个标识色相差不超过 1 度，深色底上难以分辨。
    const first = characterHue('character-1');
    const second = characterHue('character-2');
    const distance = Math.min(Math.abs(first - second), 360 - Math.abs(first - second));
    expect(distance).toBeGreaterThan(20);
  });

  it('足够多的标识能覆盖较宽的色相范围', () => {
    const hues = new Set<number>();
    for (let index = 0; index < 60; index += 1) {
      hues.add(characterHue(`preview-character-${index}`));
    }
    expect(hues.size).toBeGreaterThan(40);
  });
});

describe('avatarColors', () => {
  it('同一角色的头像配色稳定', () => {
    expect(avatarColors('preview-jin')).toEqual(avatarColors('preview-jin'));
  });

  it('底色与文字色不同，且都带该角色的色相', () => {
    const hue = characterHue('preview-jin');
    const colors = avatarColors('preview-jin');
    expect(colors.background).not.toBe(colors.foreground);
    expect(colors.background).toContain(`${hue}`);
    expect(colors.foreground).toContain(`${hue}`);
  });

  it('文字色明度高于底色，保证深色底上可读', () => {
    const colors = avatarColors('preview-jin');
    const background = Number(/oklch\(([\d.]+)%/.exec(colors.background)?.[1]);
    const foreground = Number(/oklch\(([\d.]+)%/.exec(colors.foreground)?.[1]);
    expect(foreground).toBeGreaterThan(background);
  });
});

describe('accentColor', () => {
  it('强调色与头像底色不同层明度，同一色相', () => {
    const hue = characterHue('preview-an');
    const accent = accentColor('preview-an');
    const background = avatarColors('preview-an').background;
    expect(accent).toContain(`${hue}`);
    expect(accent).not.toBe(background);
  });
});

describe('splitForBubbles', () => {
  it('短文本保持单条', () => {
    expect(splitForBubbles('今天想聊点什么？')).toEqual(['今天想聊点什么？']);
  });

  it('空文本不产生气泡', () => {
    expect(splitForBubbles('')).toEqual([]);
    expect(splitForBubbles('   ')).toEqual([]);
  });

  it('长文本在句末标点处断开', () => {
    const text = '我觉得可以先从这里开始，你觉得呢？不过也可以换一个方向。';
    const bubbles = splitForBubbles(text, 20);
    expect(bubbles.length).toBeGreaterThan(1);
    expect(bubbles.join('')).toBe(text);
  });

  it('断开后不丢失也不重复任何字符', () => {
    const text = '第一句。第二句。第三句。第四句。第五句。';
    const bubbles = splitForBubbles(text, 8);
    expect(bubbles.join('')).toBe(text);
  });

  it('没有标点的长文本按长度硬切，不会产生超长气泡', () => {
    const text = 'あ'.repeat(100);
    const bubbles = splitForBubbles(text, 30);
    expect(bubbles.every((bubble) => bubble.length <= 30)).toBe(true);
    expect(bubbles.join('')).toBe(text);
  });

  it('每个气泡都非空', () => {
    const text = '一。二。三。四。';
    for (const bubble of splitForBubbles(text, 3)) {
      expect(bubble.length).toBeGreaterThan(0);
    }
  });
});
