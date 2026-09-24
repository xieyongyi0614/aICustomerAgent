import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/core/network/events/chat_event.dart';
import 'package:mobile/features/chat/domain/chat_page_state.dart';
import 'package:mobile/features/chat/presentation/chat_page.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void main() {
  test('memory hint omitted when refs empty', () {
    const s = ChatPageState(memoryRefs: []);
    expect(s.showMemoryHint, isFalse);
    expect(s.memoryHintText.isEmpty || !s.showMemoryHint, isTrue);
  });

  test('memory hint text joins labels', () {
    const s = ChatPageState(memoryRefs: [
      MemoryRef(id: '1', kind: 'preference', label: '旅行偏好'),
      MemoryRef(id: '2', kind: 'habit', label: '预算习惯'),
    ]);
    expect(s.showMemoryHint, isTrue);
    expect(s.memoryHintText, contains('2 条长期记忆'));
    expect(s.memoryHintText, contains('旅行偏好'));
  });

  testWidgets('chat page shows hint only when refs present', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          chatPageStateProvider.overrideWith(
            () => _FixedNotifier(
              const ChatPageState(loading: false, memoryRefs: [
                MemoryRef(id: '1', kind: 'preference', label: '作息'),
              ]),
            ),
          ),
        ],
        child: MaterialApp(theme: buildAppTheme(), home: const ChatPage()),
      ),
    );
    await tester.pump();
    expect(find.textContaining('1 条长期记忆'), findsOneWidget);
  });

  testWidgets('chat page hides hint without refs', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          chatPageStateProvider.overrideWith(
            () => _FixedNotifier(const ChatPageState(loading: false)),
          ),
        ],
        child: MaterialApp(theme: buildAppTheme(), home: const ChatPage()),
      ),
    );
    await tester.pump();
    expect(find.textContaining('条长期记忆'), findsNothing);
  });
}

class _FixedNotifier extends ChatPageNotifier {
  _FixedNotifier(this._s);
  final ChatPageState _s;
  @override
  ChatPageState build() => _s;
}
