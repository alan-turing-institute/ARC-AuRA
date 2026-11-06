# 4 Research Design

In our experiments, we seek to assess the utility of our chosen dataset similarity measures in a decision criterion scenario. Here, we assume that data scientists have access to a small, labelled test set, and a larger store of unlabelled data. We focus in these experiments on unlabelled measures due to the fact the data store is unlabelled. These data scientists wish to know whether they can rely on their test set as an estimator of model performance on their data store. We seek to answer the following questions:

**Research Question 1:** *Do dataset similarity measures predict the difference in model performance between a labelled test set and an unlabelled data store?*

**Research Question 2:** *Can dataset similarity measures be thresholded for the purpose of assessing whether a given test set needs to replaced?*

In addition to addressing these questions, we also perform an initial validation of dataset similarity measure behaviour as detailed in section 5. We provide in the remainder of this section the details on the datasets used across both our validation and experiments, the design of our experiments, specific metric implementation, and the training regime used to produce models for testing our scenario.

## 4.1 Dataset Selection

For our measure validation we use DomainNet (Peng et al., 2019). DomainNet is a multiclass classification dataset with both class and domain annotations. There are six unique domains across the dataset: real, painting, clipart, quickdraw, infograph, and sketch. The presence of these domain annotations makes DomainNet well-suited to transfer learning experiments as we can easily explore transferring between domains on the same and different tasks. Furthermore, since these separate domains have a shared class-structure, this allows feature differences to be probed directly between two subsets of the data, without introducing a difference in the label space. We define in section 5 our use of DomainNet for validating our chosen dataset similarity measures.

For our primary experiments addressing RQ1 and RQ2, we use COCO (Lin et al., 2014). COCO is an object detection dataset with 80 object categories organised into 12 supercategories. As outlined in section 1, we select COCO because it enables us to better simulate the messiness of production-quality data for image classification tasks.

## 4.2 Data Partitioning and Task Construction

To simulate our decision scenario, we begin by combining the COCO 2017 train and validation splits for a total of approximately 123K images. Under a fixed seed we re-partition these into two disjoint halves: a data store, representing a generic corpus an organisation holds prior to any specific task, and a task pool, from which every task dataset is drawn.

### Figure 1 (text representation)

```text
COCO 2017 train ∪ val
123,000 images
│
├── Task pool
│   61,500 images
│   │
│   ├── Training pool 43,050
│   │   └── Task train
│   ├── Validation pool 9,225
│   │   └── Task val
│   └── Test pool 9,225
│       └── Task test ── metric, ΔAP
│
└── Data store
    61,500 images
    (fixed, unfiltered)

apply condition c
Condition c, c = 1, ..., N
```

**Figure 1:** Partition of COCO and construction of task datasets.

## 4.3 Experiments

We design three experiments to answer RQ1 and RQ2:

1. A first experiment in a binary classification setting where train and test class balance match.
2. A second experiment in a binary classification setting where test class balance varies but train balance is always 0.5.
3. A third experiment in a multilabel classificaiton setting where train and test class balance match on average.

## 4.4 Measure Implementation

Because all of our dataset similarity measures require a shared feature space between datasets, we embed the input images using DINOv3.

### 4.4.1 Maximum Mean Discrepancy

We implement MMD in PyTorch with a Gaussian RBF kernel.

### 4.4.2 Optimal Transport

We compute OT in its exact form using the Python Optimal Transport (POT) library.

### 4.4.3 Optimal Transport Dataset Distance

We compute OTDD via the otdd package (Alvarez-Melis & Fusi, 2020).

### 4.4.4 Optimal Transport Conditional Entropy

We implement OTCE via our OT (via Sinkhorn distance) and OTDD implementations.

## 4.5 Training Regime

For all experiments we fine-tune the pretrained checkpoint DINOv3-ViT-L16 pretrained on the LVD-1689M dataset.
