"""
Query Rewriting 성능 평가 스크립트.

30문제 테스트셋으로 Query Rewriting ON/OFF를 비교합니다.

평가 지표:
- 검색된 문서 수
- 응답 시간
- 문서 relevance score
- 다양성 (unique documents)
"""

import json
import time
import asyncio
from typing import List, Dict, Any
from agents.search_agent import SearchAgent
from agents.query_rewriter import query_rewriter
from utils.logger import logger


class QueryRewritingEvaluator:
    """Query Rewriting 성능 평가."""

    def __init__(self):
        """초기화."""
        self.agent = SearchAgent()
        self.results = {
            'without_rewriting': [],
            'with_rewriting': []
        }

    async def evaluate_single_question(
        self,
        question: str,
        question_id: int,
        use_rewriting: bool = True
    ) -> Dict[str, Any]:
        """
        단일 질문 평가.

        Args:
            question: 질문 텍스트
            question_id: 질문 ID
            use_rewriting: Query rewriting 사용 여부

        Returns:
            평가 결과
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[Q{question_id}] {question}")
        logger.info(f"Query Rewriting: {'ON' if use_rewriting else 'OFF'}")
        logger.info(f"{'='*60}")

        start_time = time.time()

        try:
            # Query Rewriting ON/OFF 제어
            if use_rewriting:
                # 정상 실행 (query rewriting 포함)
                result = self.agent.search(
                    question=question,
                    max_iterations=3
                )
            else:
                # Query rewriting 비활성화
                # 임시로 query_rewriter의 rewrite_query를 원본만 반환하도록 패치
                original_rewrite = query_rewriter.rewrite_query

                def mock_rewrite(original_query: str, num_variants: int = 4, session_id: str = None) -> List[str]:
                    """원본 쿼리만 반환 (rewriting 비활성화)."""
                    return [original_query]

                query_rewriter.rewrite_query = mock_rewrite

                result = self.agent.search(
                    question=question,
                    max_iterations=3
                )

                # 복원
                query_rewriter.rewrite_query = original_rewrite

            elapsed_time = time.time() - start_time

            # 결과 추출
            documents = result.get('sources', [])  # FIX: 'documents' → 'sources'
            answer = result.get('answer', '')

            # 문서 relevance score 계산 (상위 5개 평균)
            top5_scores = [doc.get('score', 0) for doc in documents[:5]]
            avg_relevance = sum(top5_scores) / len(top5_scores) if top5_scores else 0

            # Unique document IDs
            unique_doc_ids = set(doc.get('id') or doc.get('doc_id') for doc in documents)

            evaluation = {
                'question_id': question_id,
                'question': question,
                'use_rewriting': use_rewriting,
                'elapsed_time': round(elapsed_time, 2),
                'document_count': len(documents),
                'unique_document_count': len(unique_doc_ids),
                'avg_relevance_score': round(avg_relevance, 4),
                'top5_scores': [round(s, 4) for s in top5_scores],
                'answer_length': len(answer),
                'success': True
            }

            logger.info(f"✓ 완료 - 문서: {len(documents)}개, 시간: {elapsed_time:.2f}s, 관련도: {avg_relevance:.4f}")

            return evaluation

        except Exception as e:
            logger.error(f"❌ 평가 실패: {e}")

            elapsed_time = time.time() - start_time

            return {
                'question_id': question_id,
                'question': question,
                'use_rewriting': use_rewriting,
                'elapsed_time': round(elapsed_time, 2),
                'document_count': 0,
                'unique_document_count': 0,
                'avg_relevance_score': 0.0,
                'top5_scores': [],
                'answer_length': 0,
                'success': False,
                'error': str(e)
            }

    async def evaluate_all(
        self,
        test_file: str = 'test_questions_30.json'
    ) -> Dict[str, Any]:
        """
        전체 테스트 실행.

        Args:
            test_file: 테스트 질문 파일

        Returns:
            전체 평가 결과
        """
        # 테스트 질문 로드
        with open(test_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            questions = data['test_questions']

        logger.info(f"\n{'='*80}")
        logger.info(f"Query Rewriting 성능 평가 시작")
        logger.info(f"테스트 질문 수: {len(questions)}개")
        logger.info(f"{'='*80}\n")

        # Phase 1: Query Rewriting 없이 (Baseline)
        logger.info(f"\n{'#'*80}")
        logger.info("PHASE 1: Query Rewriting OFF (Baseline)")
        logger.info(f"{'#'*80}\n")

        for q in questions:
            result = await self.evaluate_single_question(
                question=q['question'],
                question_id=q['id'],
                use_rewriting=False
            )
            self.results['without_rewriting'].append(result)

            # Rate limiting (과부하 방지)
            await asyncio.sleep(1)

        # Phase 2: Query Rewriting 사용 (Improved)
        logger.info(f"\n{'#'*80}")
        logger.info("PHASE 2: Query Rewriting ON (Improved)")
        logger.info(f"{'#'*80}\n")

        for q in questions:
            result = await self.evaluate_single_question(
                question=q['question'],
                question_id=q['id'],
                use_rewriting=True
            )
            self.results['with_rewriting'].append(result)

            # Rate limiting
            await asyncio.sleep(1)

        # 통계 계산
        stats = self.calculate_statistics()

        # 결과 저장
        output = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_questions': len(questions),
            'results': self.results,
            'statistics': stats
        }

        with open('query_rewriting_evaluation_results.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"\n결과 저장: query_rewriting_evaluation_results.json")

        # 요약 출력
        self.print_summary(stats)

        return output

    def calculate_statistics(self) -> Dict[str, Any]:
        """통계 계산."""
        without = self.results['without_rewriting']
        with_rw = self.results['with_rewriting']

        def calc_avg(data: List[Dict], key: str) -> float:
            values = [d[key] for d in data if d['success']]
            return sum(values) / len(values) if values else 0

        stats = {
            'without_rewriting': {
                'avg_document_count': round(calc_avg(without, 'document_count'), 2),
                'avg_unique_document_count': round(calc_avg(without, 'unique_document_count'), 2),
                'avg_relevance_score': round(calc_avg(without, 'avg_relevance_score'), 4),
                'avg_elapsed_time': round(calc_avg(without, 'elapsed_time'), 2),
                'success_rate': round(sum(1 for d in without if d['success']) / len(without) * 100, 1)
            },
            'with_rewriting': {
                'avg_document_count': round(calc_avg(with_rw, 'document_count'), 2),
                'avg_unique_document_count': round(calc_avg(with_rw, 'unique_document_count'), 2),
                'avg_relevance_score': round(calc_avg(with_rw, 'avg_relevance_score'), 4),
                'avg_elapsed_time': round(calc_avg(with_rw, 'elapsed_time'), 2),
                'success_rate': round(sum(1 for d in with_rw if d['success']) / len(with_rw) * 100, 1)
            }
        }

        # 개선율 계산
        baseline_docs = stats['without_rewriting']['avg_document_count']
        improved_docs = stats['with_rewriting']['avg_document_count']
        doc_improvement = ((improved_docs - baseline_docs) / baseline_docs * 100) if baseline_docs > 0 else 0

        baseline_relevance = stats['without_rewriting']['avg_relevance_score']
        improved_relevance = stats['with_rewriting']['avg_relevance_score']
        relevance_improvement = ((improved_relevance - baseline_relevance) / baseline_relevance * 100) if baseline_relevance > 0 else 0

        baseline_time = stats['without_rewriting']['avg_elapsed_time']
        improved_time = stats['with_rewriting']['avg_elapsed_time']
        time_overhead = ((improved_time - baseline_time) / baseline_time * 100) if baseline_time > 0 else 0

        stats['improvement'] = {
            'document_count': round(doc_improvement, 1),
            'relevance_score': round(relevance_improvement, 1),
            'time_overhead': round(time_overhead, 1)
        }

        return stats

    def print_summary(self, stats: Dict[str, Any]):
        """요약 출력."""
        print(f"\n{'='*80}")
        print("📊 Query Rewriting 성능 평가 결과 요약")
        print(f"{'='*80}\n")

        print("🔸 Baseline (Query Rewriting OFF):")
        print(f"  - 평균 문서 수: {stats['without_rewriting']['avg_document_count']}")
        print(f"  - 평균 Unique 문서 수: {stats['without_rewriting']['avg_unique_document_count']}")
        print(f"  - 평균 Relevance Score: {stats['without_rewriting']['avg_relevance_score']}")
        print(f"  - 평균 응답 시간: {stats['without_rewriting']['avg_elapsed_time']}s")
        print(f"  - 성공률: {stats['without_rewriting']['success_rate']}%\n")

        print("🔹 Improved (Query Rewriting ON):")
        print(f"  - 평균 문서 수: {stats['with_rewriting']['avg_document_count']}")
        print(f"  - 평균 Unique 문서 수: {stats['with_rewriting']['avg_unique_document_count']}")
        print(f"  - 평균 Relevance Score: {stats['with_rewriting']['avg_relevance_score']}")
        print(f"  - 평균 응답 시간: {stats['with_rewriting']['avg_elapsed_time']}s")
        print(f"  - 성공률: {stats['with_rewriting']['success_rate']}%\n")

        print("📈 개선율:")
        improvement = stats['improvement']
        print(f"  - 문서 수: {improvement['document_count']:+.1f}%")
        print(f"  - Relevance Score: {improvement['relevance_score']:+.1f}%")
        print(f"  - 시간 오버헤드: {improvement['time_overhead']:+.1f}%\n")

        # 판정
        print(f"{'='*80}")
        if improvement['document_count'] > 10 and improvement['relevance_score'] > 5:
            print("✅ Query Rewriting 효과: 매우 우수")
            print("   → 문서 수와 관련도 모두 크게 개선")
            print("   → Reranking 없이도 목표 달성 가능")
        elif improvement['document_count'] > 5 or improvement['relevance_score'] > 5:
            print("🟢 Query Rewriting 효과: 양호")
            print("   → 일부 지표 개선 확인")
            print("   → 추가 개선을 위해 Reranking 검토 권장")
        else:
            print("🟡 Query Rewriting 효과: 제한적")
            print("   → 개선 폭이 작음")
            print("   → Reranking 추가 구현 필요")
        print(f"{'='*80}\n")


async def main():
    """메인 실행 함수."""
    evaluator = QueryRewritingEvaluator()

    try:
        await evaluator.evaluate_all('test_questions_30.json')
    except KeyboardInterrupt:
        logger.info("\n\n중단됨 (Ctrl+C)")
    except Exception as e:
        logger.error(f"\n\n평가 실패: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print(f"\n{'='*80}")
    print("Query Rewriting 성능 평가")
    print("30문제 테스트셋으로 ON/OFF 비교")
    print(f"{'='*80}\n")

    asyncio.run(main())
