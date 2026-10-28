import unittest
from imaks_kg.rag.agent_contract import ContractError, validate_call, candidate_disposition

EVENT = 'det-4220832c6ffd0c103c6e'


class ContractTests(unittest.TestCase):
    def test_client_cannot_supply_observation_or_source(self):
        for key in ('trigger_value', 'source_quote', 'path', 'gold_loaded'):
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_call('get_candidate_evidence', {'event_id': EVENT, key: 'fabricated'})

    def test_utf8_question_limit_and_empty(self):
        validate_call('search_documents', {'question': '가' * 2666})
        for value in ('가' * 2667, '  ', None):
            with self.subTest(value_type=type(value)), self.assertRaises(ContractError):
                validate_call('search_documents', {'question': value})

    def test_invalid_filters_and_pagination(self):
        for arguments in ({'offset': True}, {'limit': 21}, {'offset': -1},
                          {'sensor_id': '../../secret'}, {'kind': 'confirmed_anomaly'}, {'split': 'test'}):
            with self.subTest(arguments=arguments), self.assertRaises(ContractError):
                validate_call('list_candidates', arguments)

    def test_pagination_cannot_hide_ambiguity(self):
        result = candidate_disposition(12, [EVENT], 'explain')
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertNotIn('event_id', result)

    def test_empty_result_cannot_become_answer(self):
        self.assertEqual(candidate_disposition(0, [], 'explain')['status'], 'insufficient_evidence')
        with self.assertRaises(ContractError):
            candidate_disposition(1, [], 'explain')

    def test_unique_selection_and_listing_are_distinct(self):
        self.assertEqual(candidate_disposition(1, [EVENT], 'explain')['event_id'], EVENT)
        self.assertNotIn('event_id', candidate_disposition(1, [EVENT], 'list'))

    def test_unknown_tool_and_path_are_rejected(self):
        with self.assertRaises(ContractError):
            validate_call('execute_action', {})
        with self.assertRaises(ContractError):
            validate_call('get_candidate_evidence', {'event_id': '../events.json'})


if __name__ == '__main__':
    unittest.main()
