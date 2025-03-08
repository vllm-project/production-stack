import os

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

stack_results = []
qpses = []
for qps in np.arange(0.3, 1.2, 0.2):
    # round qps to 1 decimal
    q = round(qps, 1)
    file = f"stack_output_{q}.csv"
    if not os.path.exists(file):
        continue
    qpses += [q]
    # Read csv file
    data = pd.read_csv(file)["ttft"].tolist()
    stack_results.append(sum(data) / len(data))
print(stack_results)

plt.plot(
    qpses,
    stack_results,
    label="Production Stack",
    marker="x",
    color="blue",
    linewidth=2,
    markersize=8,
)
aibrix_results = []
qpses = []
for qps in np.arange(0.3, 1.2, 0.2):
    # round qps to 1 decimal
    q = round(qps, 1)

    file = f"aibrix_output_{q}.csv"
    if not os.path.exists(file):
        continue
    qpses += [q]
    # Read csv file
    data = pd.read_csv(file)["ttft"].tolist()
    aibrix_results.append(sum(data) / len(data))
print(aibrix_results)
plt.plot(
    qpses,
    aibrix_results,
    label="Aibrix",
    marker="o",
    color="red",
    linewidth=2,
    markersize=8,
)

native_results = []
for qps in np.arange(0.3, 1.2, 0.2):
    # round qps to 1 decimal
    q = round(qps, 1)
    file = f"native_output_{q}.csv"
    # Read csv file
    data = pd.read_csv(file)["ttft"].tolist()
    native_results.append(sum(data) / len(data))
plt.plot(np.arange(0.3, 1.2, 0.2), native_results, label="Native K8S")


plt.xlim(left=0)
plt.ylim(top=10)
plt.xlabel("QPS")
plt.ylabel("Average Time to First Token (s)")
plt.title("Average Time to First Token vs QPS")
plt.savefig("figure.png")
