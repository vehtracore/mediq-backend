import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediq_app/src/core/constants/mdq_ai_assets.dart';
import 'package:mediq_app/src/features/chat/presentation/ai_chat_screen.dart';
import 'package:mediq_app/src/features/patient_dashboard/patient_home_screen.dart';

Widget _host(Widget child) => MaterialApp(home: Scaffold(body: child));

String _assetName(WidgetTester tester, Finder finder) {
  final image = tester.widget<Image>(finder);
  return (image.image as AssetImage).assetName;
}

void main() {
  testWidgets('dashboard AI card uses the Q Lens asset without overflow',
      (tester) async {
    var wasTapped = false;
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _host(AiSymptomCheckerCard(onTap: () => wasTapped = true)),
    );

    final mark = find.byKey(const ValueKey('mdq-ai-lens'));
    expect(mark, findsOneWidget);
    expect(_assetName(tester, mark), MdqAiAssets.lens);
    await tester.tap(find.byType(AiSymptomCheckerCard));
    expect(wasTapped, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('AI chat welcome state uses the Q Conversation asset',
      (tester) async {
    await tester.pumpWidget(_host(const AiChatWelcomeState()));

    final mark = find.byKey(const ValueKey('mdq-ai-conversation'));
    expect(mark, findsOneWidget);
    expect(_assetName(tester, mark), MdqAiAssets.conversation);
    expect(tester.takeException(), isNull);
  });
}
