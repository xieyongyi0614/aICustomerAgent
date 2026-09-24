/// 增量 Markdown：已闭合块完整解析，尾部未闭合块按纯文本。
class IncrementalMarkdown {
  const IncrementalMarkdown();

  /// 将 [source] 切成 (closedBlocks, openTail)。
  /// closedBlocks 可交给 Markdown 完整渲染；openTail 仅作纯文本。
  (String, String) split(String source) {
    if (source.isEmpty) return ('', '');
    final lines = source.split('\n');
    var lastClosedEnd = -1;
    var i = 0;
    while (i < lines.length) {
      final line = lines[i];
      if (_isBlockStart(line)) {
        final end = _findBlockEnd(lines, i);
        if (end == null) break;
        lastClosedEnd = end;
        i = end + 1;
        continue;
      }
      // 普通行：若后面还有内容则视为已闭合段落边界（空行或块起始）
      if (i + 1 < lines.length &&
          (lines[i + 1].isEmpty || _isBlockStart(lines[i + 1]))) {
        lastClosedEnd = i;
      }
      i += 1;
    }
    if (lastClosedEnd < 0) {
      return ('', source);
    }
    final closed = lines.sublist(0, lastClosedEnd + 1).join('\n');
    final open = lines.sublist(lastClosedEnd + 1).join('\n');
    return (closed, open);
  }

  bool _isBlockStart(String line) {
    final t = line.trimLeft();
    return t.startsWith('#') ||
        t.startsWith('```') ||
        t.startsWith('- ') ||
        t.startsWith('* ') ||
        t.startsWith('> ') ||
        t.startsWith('| ');
  }

  int? _findBlockEnd(List<String> lines, int start) {
    final first = lines[start].trimLeft();
    if (first.startsWith('```')) {
      for (var i = start + 1; i < lines.length; i++) {
        if (lines[i].trimLeft().startsWith('```')) return i;
      }
      return null;
    }
    if (first.startsWith('- ') || first.startsWith('* ')) {
      var end = start;
      for (var i = start + 1; i < lines.length; i++) {
        final t = lines[i].trimLeft();
        if (t.startsWith('- ') || t.startsWith('* ') || t.isEmpty) {
          if (t.isEmpty) return end;
          end = i;
          continue;
        }
        return end;
      }
      return end;
    }
    if (first.startsWith('| ')) {
      var end = start;
      for (var i = start + 1; i < lines.length; i++) {
        if (lines[i].trimLeft().startsWith('| ')) {
          end = i;
          continue;
        }
        return end;
      }
      return end;
    }
    // 标题 / 引用：单行块
    return start;
  }
}
