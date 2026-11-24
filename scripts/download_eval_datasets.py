"""
Offline download and prep documentation script for large evaluation datasets.
Usage: python scripts/download_eval_datasets.py [--dataset cuad|contract_nli|finqa] [--sample 10]
Note: Does not download automatically during test runs or build steps.
"""
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Download public evaluation datasets for contradiction auditing.")
    parser.add_argument("--dataset", choices=["cuad", "contract_nli", "finqa", "tatqa", "financebench", "all"], default="all")
    parser.add_argument("--sample", type=int, default=10, help="Number of samples to extract.")
    args = parser.parse_args()

    print(f"Dataset preparation utility for: {args.dataset}")
    print("Zero automatic large downloads policy active. Samples can be mirrored to eval/data/fixtures/.")
    print("Download instructions:")
    print("  CUAD: https://www.atticusprojectai.org/cuad")
    print("  ContractNLI: https://stanfordnlp.github.io/contract-nli/")
    print("  FinQA: https://github.com/czyssrs/FinQA")
    print("  TAT-QA: https://github.com/NExT-Plus/TAT-QA")

if __name__ == "__main__":
    main()
