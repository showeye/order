# analyze_logs.py

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd

LOG_PREFIX_TOOL = "order_assistant.OrderAssistant._tool_"
LOGS_DIR = "order/tests/logs"
REPORTS_DIR = "order/tests/reports"
GROUND_TRUTH_FILE = "order/tests/ground_truth.json"


def load_ground_truth(file_path: str) -> Dict[str, Dict[str, Any]]:
    """Loads ground truth data from a JSON file."""
    if not os.path.exists(file_path):
        print(f"Error: Ground truth file not found at {file_path}")
        sys.exit(1)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            ground_truth = json.load(f)
        print(f"Successfully loaded ground truth from {file_path}")
        return ground_truth
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading ground truth file {file_path}: {e}")
        sys.exit(1)


def parse_log_file_with_timestamps(log_file_path: str) -> Tuple[
    Dict[str, List[Dict[str, Any]]], # logs_by_test_case
    Optional[datetime],              # overall_min_timestamp
    Optional[datetime],              # overall_max_timestamp
    Dict[str, Tuple[Optional[datetime], Optional[datetime]]] # timestamps_by_test_case
]:
    """
    Parses a JSON log file, groups entries by test_case_id,
    extracts overall min/max timestamps, and min/max timestamps per test_case_id.
    """
    if not os.path.exists(log_file_path):
        print(f"Error: Log file not found at {log_file_path}")
        return {}, None, None, {}

    logs_by_test_case = defaultdict(list)
    timestamps_by_test_case = defaultdict(lambda: [None, None]) # [min_ts, max_ts]
    overall_min_timestamp = None
    overall_max_timestamp = None

    print(f"Analyzing log file: {log_file_path}")
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    log_entry = json.loads(line.strip())

                    # Extract and parse timestamp
                    timestamp_str = log_entry.get("timestamp")
                    current_timestamp = None
                    if timestamp_str:
                        try:
                            # Handle the literal '.%fZ' if present by removing it
                            cleaned_timestamp_str = timestamp_str.replace('.%fZ', 'Z')
                            # Parse standard ISO format, replacing Z with UTC offset
                            current_timestamp = datetime.fromisoformat(cleaned_timestamp_str.replace('Z', '+00:00'))

                            # Update overall min/max timestamps
                            if overall_min_timestamp is None or current_timestamp < overall_min_timestamp:
                                overall_min_timestamp = current_timestamp
                            if overall_max_timestamp is None or current_timestamp > overall_max_timestamp:
                                overall_max_timestamp = current_timestamp

                        except ValueError:
                             print(f"Warning: Skipping line {line_num}, invalid timestamp format: {timestamp_str}")
                             current_timestamp = None # Ensure timestamp is None if parsing failed

                    # Process entry if associated with a test case
                    test_case_id = log_entry.get("test_case_id")
                    if test_case_id:
                        logs_by_test_case[test_case_id].append(log_entry)
                        # Update min/max timestamps for this specific test case if timestamp is valid
                        if current_timestamp:
                            case_min_ts, case_max_ts = timestamps_by_test_case[test_case_id]
                            if case_min_ts is None or current_timestamp < case_min_ts:
                                timestamps_by_test_case[test_case_id][0] = current_timestamp
                            if case_max_ts is None or current_timestamp > case_max_ts:
                                timestamps_by_test_case[test_case_id][1] = current_timestamp

                except json.JSONDecodeError:
                    print(f"Warning: Skipping non-JSON line {line_num}: {line.strip()}")
                except Exception as e:
                    print(f"Warning: Error processing line {line_num}: {e} - Line: {line.strip()}")
    except Exception as e:
        print(f"Error reading log file {log_file_path}: {e}")
        return {}, None, None, {}

    if logs_by_test_case:
        print(f"Found log entries for {len(logs_by_test_case)} unique test cases.")
    if overall_min_timestamp and overall_max_timestamp:
        print(f"Log timestamps range from {overall_min_timestamp.isoformat()} to {overall_max_timestamp.isoformat()}")
    else:
         print("Warning: Could not determine overall time range from log file.")

    final_timestamps_by_case = {k: tuple(v) for k, v in timestamps_by_test_case.items()}

    return logs_by_test_case, overall_min_timestamp, overall_max_timestamp, final_timestamps_by_case


def compare_params(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    """
    Compares expected parameters against actual parameters.
    Checks if all expected keys are present in actual and have matching values.
    Ignores extra keys present in actual but not in expected.
    Handles None values flexibly if needed (currently strict comparison).
    """
    if expected is None:
        return actual is None
    if actual is None:
        return False

    for key, expected_value in expected.items():
        if key not in actual:
            print(f"    PARAM FAIL: Missing expected key '{key}'")
            return False
        actual_value = actual[key]

        if expected_value != actual_value:
            print(f"    PARAM FAIL: Mismatch for key '{key}'. Expected: {expected_value}, Got: {actual_value}")
            return False
    return True


def find_tool_call_logs(test_logs: List[Dict[str, Any]]) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Finds the primary tool call entry and exit logs for a test case."""
    tool_entry_log = None
    tool_exit_log = None
    # Iterate through logs to find the first tool entry and its corresponding exit
    for log in test_logs:
        func_name = log.get("function", "")
        event = log.get("event")
        if event == "entry" and func_name.startswith(LOG_PREFIX_TOOL):
            tool_entry_log = log
            # Look for the corresponding exit log (simple match by func name for now)
            for exit_log in test_logs:
                if (exit_log.get("event") == "exit" and
                        exit_log.get("function") == func_name):
                     # Basic check: ensure exit is after entry (requires timestamp comparison ideally)
                     # Simplification: assume first exit for the func name is the one
                     tool_exit_log = exit_log
                     break # Found entry and potential exit
            break # Process only the first tool call initiated by the agent per test case

    return tool_entry_log, tool_exit_log

def analyze_test_case(test_id: str,
                      test_logs: List[Dict[str, Any]],
                      ground_truth: Dict[str, Any],
                      test_timestamps: Tuple[Optional[datetime], Optional[datetime]]
                      ) -> Dict[str, Any]:
    """Analyzes logs for a single test case against ground truth."""
    print(f"\nAnalyzing Test Case: {test_id}")
    results = {
        "test_id": test_id,
        "tool_selected_correctly": None,
        "params_extracted_correctly": None,
        "tool_call_succeeded": None, # Technical success/failure
        "correct_tool_invocation": None,
        "cancellation_flow_compliant": None,
        "tool_call_duration_ms": None,
        "test_case_duration_seconds": None,
        "tool_call_attempted": False,
        "is_cancel_check_test": False,
        "expected_tool_failure": ground_truth.get("expects_tool_failure", False)
    }

    # Calculate test case duration
    start_ts, end_ts = test_timestamps
    if start_ts and end_ts and start_ts <= end_ts:
        duration = end_ts - start_ts
        results["test_case_duration_seconds"] = round(duration.total_seconds(), 2)
        print(f"  - Test Case Duration: {results['test_case_duration_seconds']} seconds")
    else:
        print("  - Test Case Duration: Could not determine (missing timestamps)")


    expected_tool_simple_name = ground_truth.get("expected_tool")
    expected_params = ground_truth.get("expected_params")
    expected_confirmation = ground_truth.get("expected_confirmation_needed", False)
    results["is_cancel_check_test"] = expected_tool_simple_name == "_tool_cancel_order_check"

    tool_entry_log, tool_exit_log = find_tool_call_logs(test_logs)

    if not expected_tool_simple_name:
         print("  - No tool call expected by ground truth.")
         if tool_entry_log:
              print(f"  - FAIL: Tool '{tool_entry_log.get('function')}' was called unexpectedly.")
              results["tool_selected_correctly"] = False
         else:
              print("  - OK: No tool call occurred, as expected.")
              results["tool_selected_correctly"] = True
              results["params_extracted_correctly"] = True
              results["tool_call_succeeded"] = True # Technically succeeded (no call)
              results["correct_tool_invocation"] = True
         return results

    # Tool Call Expected
    if not tool_entry_log:
        print(f"  - FAIL: Expected tool '{expected_tool_simple_name}' but no tool call found in logs.")
        results["tool_selected_correctly"] = False
        results["tool_call_succeeded"] = False # Failed as it wasn't called
        return results

    results["tool_call_attempted"] = True
    actual_tool_full_name = tool_entry_log.get("function", "")
    actual_tool_simple_name = actual_tool_full_name.split('.')[-1]
    actual_params = tool_entry_log.get("f_kwargs", {})

    # 1. Tool Selection
    if actual_tool_simple_name == expected_tool_simple_name:
        print(f"  - Tool Selection: CORRECT ({actual_tool_simple_name})")
        results["tool_selected_correctly"] = True
    else:
        print(f"  - Tool Selection: FAIL (Expected: {expected_tool_simple_name}, Got: {actual_tool_simple_name})")
        results["tool_selected_correctly"] = False
        results["params_extracted_correctly"] = False
        results["correct_tool_invocation"] = False
        # Still check technical success/failure even if wrong tool
        if tool_exit_log:
             results["tool_call_succeeded"] = tool_exit_log.get("exception") is None
             results["tool_call_duration_ms"] = tool_exit_log.get("duration_ms")
        else:
             results["tool_call_succeeded"] = False # Missing exit log is a failure
        return results

    # 2. Parameter Extraction (only if tool selection was correct)
    if compare_params(expected_params, actual_params):
        print(f"  - Parameter Extraction: CORRECT ({actual_params})")
        results["params_extracted_correctly"] = True
    else:
        print(f"  - Parameter Extraction: FAIL (Expected: {expected_params}, Got: {actual_params})")
        results["params_extracted_correctly"] = False

    # 3. Tool Call Success Rate (Technical execution) - Record True/False
    if tool_exit_log:
        if tool_exit_log.get("exception") is None:
            print("  - Tool Call Execution: SUCCEEDED (No exception)")
            results["tool_call_succeeded"] = True
            results["tool_call_duration_ms"] = tool_exit_log.get("duration_ms")
            if results["expected_tool_failure"]:
                 print("    - NOTE: Tool call succeeded but failure was expected by ground truth.")
        else:
            exception_info = tool_exit_log.get('exception', {}).get('type', 'Unknown Exception')
            print(f"  - Tool Call Execution: FAILED (Exception: {exception_info})")
            results["tool_call_succeeded"] = False
            results["tool_call_duration_ms"] = tool_exit_log.get("duration_ms")
            if results["expected_tool_failure"]:
                 print("    - NOTE: Tool call failed as expected by ground truth.")
    else:
        print("  - Tool Call Execution: UNKNOWN (Exit log not found)")
        results["tool_call_succeeded"] = False # Treat missing exit as failure

    # 4. Correct Tool Invocation (Correct tool AND correct params)
    results["correct_tool_invocation"] = (results["tool_selected_correctly"] and
                                          results["params_extracted_correctly"])
    print(f"  - Correct Invocation (Tool & Params): {results['correct_tool_invocation']}")


    # 5. Cancellation Flow Compliance
    if results["is_cancel_check_test"]:
        returned_value = tool_exit_log.get("return_value") if tool_exit_log else None
        eligible_in_log = False
        if isinstance(returned_value, dict):
            eligible_in_log = returned_value.get("eligible_for_confirmation", False)

        if eligible_in_log == expected_confirmation:
             print(f"  - Cancellation Flow: COMPLIANT (Eligible: {eligible_in_log}, Expected: {expected_confirmation})")
             results["cancellation_flow_compliant"] = True
        else:
             print(f"  - Cancellation Flow: FAIL (Eligible: {eligible_in_log}, Expected: {expected_confirmation})")
             results["cancellation_flow_compliant"] = False

    return results


def calculate_metrics(all_results: List[Dict[str, Any]],
                      start_time: Optional[datetime],
                      end_time: Optional[datetime]) -> Dict[str, Any]:
    """Aggregates analysis results and calculates final metrics."""
    metrics = {
        "total_test_cases_analyzed": 0,
        "tool_calls_attempted": 0,
        "tool_selection_correct": 0,
        "params_extraction_correct": 0,
        "tool_calls_succeeded_raw": 0, # Raw count of technical successes
        "tool_calls_failed_raw": 0,   # Raw count of technical failures
        "relevant_tool_calls_for_success_rate": 0, # Denominator for success rate %
        "successful_relevant_tool_calls": 0,       # Numerator for success rate %
        "correct_tool_invocations": 0,
        "cancellation_tests": 0,
        "cancellation_flow_compliant": 0,
        "total_successful_tool_call_duration_ms": 0,
        "successful_tool_calls_for_latency": 0,
        "total_test_case_duration_seconds": 0,
        "test_cases_with_duration": 0,
        "total_execution_time_seconds": None,
    }

    for r in all_results:
        metrics["total_test_cases_analyzed"] += 1

        if r.get("tool_call_attempted"):
            metrics["tool_calls_attempted"] += 1

            # Raw Success/Failure Counts
            if r["tool_call_succeeded"] is True:
                metrics["tool_calls_succeeded_raw"] += 1
                if r["tool_call_duration_ms"] is not None:
                     metrics["total_successful_tool_call_duration_ms"] += r["tool_call_duration_ms"]
                     metrics["successful_tool_calls_for_latency"] += 1
            elif r["tool_call_succeeded"] is False: # Explicitly check for False
                 metrics["tool_calls_failed_raw"] += 1

            # Success Rate Calculation (excluding expected failures)
            # Only consider this call for the rate if failure wasn't expected
            if not r.get("expected_tool_failure"):
                metrics["relevant_tool_calls_for_success_rate"] += 1
                if r["tool_call_succeeded"] is True:
                    metrics["successful_relevant_tool_calls"] += 1

            # Other Metrics (based on attempted calls)
            if r["tool_selected_correctly"] is True:
                metrics["tool_selection_correct"] += 1
            if r["params_extracted_correctly"] is True:
                metrics["params_extraction_correct"] += 1
            if r["correct_tool_invocation"] is True:
                metrics["correct_tool_invocations"] += 1

        if r.get("is_cancel_check_test"):
             metrics["cancellation_tests"] += 1
             if r["cancellation_flow_compliant"] is True:
                  metrics["cancellation_flow_compliant"] += 1

        # Aggregate test case duration
        if r.get("test_case_duration_seconds") is not None:
            metrics["total_test_case_duration_seconds"] += r["test_case_duration_seconds"]
            metrics["test_cases_with_duration"] += 1

    # Calculate total execution time for the whole log file
    if start_time and end_time and start_time <= end_time:
        total_duration = end_time - start_time
        metrics["total_execution_time_seconds"] = round(total_duration.total_seconds(), 2)


    # Calculate Percentages and Averages
    metrics["tool_selection_accuracy_%"] = (metrics["tool_selection_correct"]
                                            / metrics["tool_calls_attempted"] * 100
                                         if metrics["tool_calls_attempted"] > 0 else 0)
    metrics["parameter_extraction_accuracy_%"] = (metrics["params_extraction_correct"]
                                                  / metrics["tool_calls_attempted"] * 100
                                            if metrics["tool_calls_attempted"] > 0 else 0)

    metrics["tool_call_success_rate_%"] = (metrics["successful_relevant_tool_calls"]
                                           / metrics["relevant_tool_calls_for_success_rate"] * 100
                                         if metrics["relevant_tool_calls_for_success_rate"] > 0 else 0)
    metrics["correct_tool_invocation_rate_%"] = (metrics["correct_tool_invocations"]
                                                 / metrics["tool_calls_attempted"] * 100
                                                if metrics["tool_calls_attempted"] > 0 else 0)
    metrics["cancellation_flow_compliance_%"] = (metrics["cancellation_flow_compliant"]
                                                 / metrics["cancellation_tests"] * 100
                                                  if metrics["cancellation_tests"] > 0 else 0)
    metrics["average_tool_latency_ms"] = (metrics["total_successful_tool_call_duration_ms"]
                                     / metrics["successful_tool_calls_for_latency"]
                                     if metrics["successful_tool_calls_for_latency"] > 0 else 0)
    metrics["average_test_case_duration_seconds"] = (metrics["total_test_case_duration_seconds"]
                                                    / metrics["test_cases_with_duration"]
                                                    if metrics["test_cases_with_duration"] > 0 else 0)

    return metrics

def print_metrics(metrics: Dict[str, Any]):
    """Calculates and saves metrics to CSV and a formatted text report file.

    Args:
        metrics: A dictionary containing the calculated metric values.
    """
    # Prepare Report Content
    success_numerator = metrics.get('successful_relevant_tool_calls', 0)
    success_denominator = metrics.get('relevant_tool_calls_for_success_rate', 0)
    success_rate_percent = metrics.get('tool_call_success_rate_%', 0.0)

    report_lines = [
        "--- Final Metrics ---",
        f"Total Test Cases Analyzed: {metrics['total_test_cases_analyzed']}",
        f"Test Cases Attempting Tool Calls: {metrics['tool_calls_attempted']}",
        f"Total Execution Time (Log File): {metrics.get('total_execution_time_seconds', 'N/A')} seconds",
        f"Average Test Case Duration: {metrics.get('average_test_case_duration_seconds', 0.0):.2f} seconds",
        "-" * 20,
        f"Tool Selection Accuracy: {metrics.get('tool_selection_accuracy_%', 0.0):.2f}% "
        f"({metrics.get('tool_selection_correct', 0)}/{metrics.get('tool_calls_attempted', 0)})",
        f"Parameter Extraction Accuracy: {metrics.get('parameter_extraction_accuracy_%', 0.0):.2f}% "
        f"({metrics.get('params_extraction_correct', 0)}/{metrics.get('tool_calls_attempted', 0)})",
        f"Correct Tool Invocation Rate: {metrics.get('correct_tool_invocation_rate_%', 0.0):.2f}% "
        f"({metrics.get('correct_tool_invocations', 0)}/{metrics.get('tool_calls_attempted', 0)})",
        f"Tool Call Success Rate (Technical, Excl. Expected Failures): {success_rate_percent:.2f}% "
        f"({success_numerator}/{success_denominator})",
        f"Average Tool Execution Latency (Successful Calls): {metrics.get('average_tool_latency_ms', 0.0):.2f} ms",
        f"Cancellation Flow Compliance: {metrics.get('cancellation_flow_compliance_%', 0.0):.2f}% "
        f"({metrics.get('cancellation_flow_compliant', 0)}/{metrics.get('cancellation_tests', 0)})",
        "-" * 20
    ]

    # Print to Console
    print("\n".join(report_lines))

    # Save to Files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = REPORTS_DIR

    try:
        os.makedirs(report_dir, exist_ok=True)
    except OSError as e:
        print(f"Error creating directory {report_dir}: {e}")
        return

    text_report_path = os.path.join(report_dir, f'metrics_summary_{timestamp}.txt')
    csv_report_path = os.path.join(report_dir, f'metrics_data_{timestamp}.csv')

    # Save text report
    try:
        with open(text_report_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        print(f"\nMetrics summary saved to: {text_report_path}")
    except IOError as e:
        print(f"Error saving text report to {text_report_path}: {e}")

    # Save CSV report
    try:
        # Create a Pandas Series from the metrics dictionary for the summary CSV
        metrics_to_save = {
            k: v
            for k, v in metrics.items()
            if not k.startswith('total_') or k == "total_execution_time_seconds"
        }
        # Ensure the main percentage is included, even if intermediate counters are filtered out
        metrics_to_save['tool_call_success_rate_%'] = metrics['tool_call_success_rate_%']

        metrics_series = pd.Series(metrics_to_save)
        metrics_series.name = "Value"
        metrics_series.index.name = "Metric"
        metrics_series.to_csv(csv_report_path, header=True)
        print(f"Metrics data saved to: {csv_report_path}")
    except ImportError:
         print("Error saving CSV report: pandas library not found. Please install pandas.")
    except Exception as e:
        print(f"Error saving CSV report to {csv_report_path}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze order assistant logs against ground truth.")
    parser.add_argument(
        "log_file",
        nargs='?',
        type=str,
        help="Path to the specific JSON log file to analyze. If omitted, the latest log file in "
             f"'{LOGS_DIR}' will be used."
    )
    parser.add_argument(
        "--gt",
        type=str,
        default=GROUND_TRUTH_FILE,
        help=f"Path to the ground truth JSON file (default: {GROUND_TRUTH_FILE})"
    )
    args = parser.parse_args()

    log_path = args.log_file
    gt_path = args.gt

    # Find latest log file if not specified
    if log_path is None:
        print(f"No log file specified, searching for the latest log in '{LOGS_DIR}'...")
        if not os.path.isdir(LOGS_DIR):
            print(f"Error: Log directory '{LOGS_DIR}' not found.")
            sys.exit(1)
        list_of_log_files = glob.glob(os.path.join(LOGS_DIR, 'evaluation_*.log'))
        if not list_of_log_files:
            print(f"Error: No log files found matching 'evaluation_*.log' in '{LOGS_DIR}'.")
            sys.exit(1)
        latest_log_file = max(list_of_log_files, key=os.path.basename)
        print(f"Using latest log file: {latest_log_file}")
        log_path = latest_log_file

    ground_truth_data = load_ground_truth(gt_path)
    # Use the updated parsing function to get per-case timestamps
    logs_by_test_case, overall_start_ts, overall_end_ts, timestamps_by_case = parse_log_file_with_timestamps(log_path)

    all_test_results = []
    processed_test_ids = set()

    # Analyze logs for test cases present in the log file
    for test_id, logs in logs_by_test_case.items():
        if test_id in ground_truth_data:
            # Get the specific timestamps for this test case
            case_timestamps = timestamps_by_case.get(test_id, (None, None))
            # Pass the timestamps to the analysis function
            analysis = analyze_test_case(test_id, logs, ground_truth_data[test_id], case_timestamps)
            all_test_results.append(analysis)
            processed_test_ids.add(test_id)
        else:
            print(f"Warning: Logs found for test_id '{test_id}' but no ground truth entry exists. Skipping.")

    # Check for ground truth entries that didn't have corresponding logs
    for test_id in ground_truth_data:
        if test_id not in processed_test_ids:
             print(f"Warning: Ground truth exists for '{test_id}' but no logs found for it in this file.")

    if not all_test_results and not logs_by_test_case:
        print("\nNo test cases could be analyzed (log file might be empty or lack test_case_id).")
    else:
        # Pass overall timestamps to calculate_metrics
        final_metrics = calculate_metrics(all_test_results, overall_start_ts, overall_end_ts)
        print_metrics(final_metrics)