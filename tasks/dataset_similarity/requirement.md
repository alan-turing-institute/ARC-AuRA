We are interested in dataset similarity metrics in 3 high-level scenarios:
1.	Whether a training dataset is sufficiently representative of/in distribution for a target dataset.
2.	Whether a target dataset is sufficiently in-domain for a pre-existing model.
3.	Whether an individual sample is out of distribution for a model (or dataset), in a way that matters for the model’s likely performance.

ARC has previously done work using dataset similarity metrics such as Optimal Transport Dataset Distance (OTDD). Limitations of the OTDD paper include that it is now more than 5 years since its publication, and that the experiments in it are mostly on simple datasets, such as CIFAR-10.

We would like to explore:
1.	Whether there have been new developments in the SOTA for dataset similarity measures since the OTDD paper.
2.	Whether OTDD, or other metrics, have been demonstrated on more realistic datasets and dataset differences.

If the answer to 1) is no and to 2) is yes, this could be a short project scoped to a brief literature review with recommendations. If the answer to 2), in particular, is no then the project can expand into running experiments to determine the performance of similarity measures in more realistic scenarios. This could include, for example:
-	Introducing new classes to a dataset (e.g. a new breed of dog to a dataset of dog breeds)
-	Introducing data from the same classes but from a different context (e.g. start with dogs in the arctic and cats in the desert, introduce dogs in the desert).
-	Introducing completely different types of data (e.g. start with photography of objects, introduce photography of animals or non-photographic images e.g. document scans)
-	Varying image quality
