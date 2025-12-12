#!/bin/bash
echo "🔍 10문제 평가 테스트 모니터링 시작"
echo "======================================"
echo ""

while true; do
    # Check if process is still running
    if ! pgrep -f "evaluate_query_rewriting.py test_questions_10_sample.json" > /dev/null; then
        echo ""
        echo "✅ 테스트 완료!"
        echo ""
        
        if [ -f query_rewriting_evaluation_results.json ]; then
            echo "📊 최종 결과:"
            echo "============"
            jq '.statistics' query_rewriting_evaluation_results.json
            
            echo ""
            echo "📈 개선율:"
            jq '.statistics.improvement' query_rewriting_evaluation_results.json
        else
            echo "❌ 결과 파일을 찾을 수 없습니다"
        fi
        break
    fi
    
    # Show progress
    PHASE1_COUNT=$(grep -c "Query Rewriting: OFF" evaluation_10q.log 2>/dev/null || echo 0)
    PHASE2_COUNT=$(grep -c "Query Rewriting: ON" evaluation_10q.log 2>/dev/null || echo 0)
    TOTAL_DONE=$((PHASE1_COUNT + PHASE2_COUNT))
    
    echo -ne "\r⏳ 진행 중: ${TOTAL_DONE}/20 완료 (PHASE1: ${PHASE1_COUNT}/10, PHASE2: ${PHASE2_COUNT}/10)  "
    
    sleep 10
done
