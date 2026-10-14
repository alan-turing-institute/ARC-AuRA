# 2 Notation

Across this report we define unlabelled datasets as a set of records drawn from a given feature space:

```text
D = {x_i}^n_{i=1}, x_i ∈ X
```

where x_i is the ith record in the dataset and X is the feature space, such as the space of 32 × 32 pixel images with 3 colour channels, which is the space to which all CIFAR-10 images belong. Note that a shared feature space for all records is typically not true of realistic unstructured datasets (e.g. images can be different sizes). However, all dataset similarity measures not only assume such a feature space, but also make the stronger assumption that both input datasets D_A and D_B are collections of records from the same feature space:

```text
∀x ∈ (D_A ∪ D_B)  x ∈ X
```

We discuss in subsection 7.2 some possible routes to relaxing the requirement above. For the purposes of this report, this means that for realistic settings dataset similarity measures are implicitly parameterised by the use of a method for embedding the records of datasets in the same feature space.

We define labelled datasets as a set of records comprised of feature-label pairs:

```text
D = {(x_i,y_i)}^n_{i=1}, (x_i,y_i) ∈ X × Y
```

where y_i is the label for the ith record in the dataset and Y is a label space, such as the space of all CIFAR-10 class labels.

# 3 Dataset Similarity Measures

Dataset similarity measures aim to estimate the extent to which two datasets are ‘similar’ to one another. Because the notion of similarity can be difficult to define, extant research has typically validated these measures by assessing whether they possess properties implied by the notion of similarity.

This includes:

1. Whether the measure satisfies the criteria to be defined as a metric.
2. Whether the measure is predictive of transfer learning success.
3. Whether the measure is predictive of transfer attack success using adversarial examples.

Dataset similarity measures can be taxonomised in a number of ways. First, these measures differ in whether they take dataset labels as inputs or not. We refer to those that do not as unlabelled measures and those that do as labelled measures.

Second, most dataset similarity measures are in fact dissimilarity measures bounded on [0,∞), with a value of 0 denoting identity and higher values denoting increasing amounts of dissimilarity.

Finally, dataset similarity measures can be further taxonomised according to the method by which similarity is computed. Stolte et al. (2024) produce such a taxonomy from 118 dataset similarity measures, producing 10 total classes.

## 3.1 Maximum Mean Discrepancy

Given a positive-semidefinite kernel K : X × X → R, the maximum mean discrepancy (MMD) for two datasets D_A and D_B is given by Equation (4) in the report.

Intuitively, the kernel K is used to produce the elements of a similarity matrix between the records in two input datasets. MMD is based on comparing intra-dataset to inter-dataset pointwise distances between samples as embedded by the kernel.

If D_A = D_B, then MMD(D_A,D_B) = 0 by construction. As points in the two datasets become increasingly different, MMD increases in size.

## 3.2 Optimal Transport

Optimal transport (OT) is the problem of finding the most efficient method for transforming one distribution into another.

In the Kantorovich formulation, given two distributions P_A and P_B, optimal transport is the search for a joint distribution π that minimises transport cost.

Intuitively, the optimal transport plan is the one which minimises overall cost as weighted by the mass being transferred between the two distributions.

To apply this to dataset similarity, both datasets are treated as empirical probability distributions by assigning equal probability to each sample.

## 3.3 Sinkhorn Distance and Divergence

Optimal transport is sometimes computed with a regularisation term and is then called the Sinkhorn distance.

The use of regularisation enables the much faster Sinkhorn-Knopp algorithm to be used. However, regularisation produces more diffuse and thus less optimal transport plans.

A second problem is that Sinkhorn distance no longer satisfies the identity of indiscernibles. To address this, Sinkhorn divergence is computed:

```text
SD(D_A,D_B) = OT_Sinkhorn(D_A,D_B)
            - 1/2 OT_Sinkhorn(D_A,D_A)
            - 1/2 OT_Sinkhorn(D_B,D_B)
```

This restores the identity of indiscernibles and therefore satisfies the criterion to be a metric.

## 3.4 Optimal Transport Dataset Distance

Optimal Transport Dataset Distance (OTDD) is an optimal-transport based measure that incorporates label information.

The key idea is to define distances between labels using optimal transport between the distributions of features associated with those labels. OTDD uses these label distances within a larger optimal transport problem to define a distance directly between datasets.

A useful consequence of this approach is that there is no requirement for the label spaces of D_A and D_B to be shared because label distances are based on feature distributions.

## 3.5 Optimal Transport Conditional Entropy

Optimal Transport Conditional Entropy (OTCE) combines optimal transport with a measure of task difference.

Transfer performance is decomposed into:

- Domain difference (W_D)
- Task difference (W_T)

The task-difference term is computed using the optimal transport plan and the labels of both datasets.

The final OTCE score is:

```text
OTCE = λ1 W_D + λ2 W_T + b
```

where λ1, λ2 and b are hyperparameters.

By defining dataset similarity on these two components, OTCE is intended to provide a more interpretable measure of transfer performance than metrics that treat transferability as a single quantity.
