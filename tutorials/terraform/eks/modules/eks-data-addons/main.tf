data "aws_partition" "current" {}
data "aws_region" "current" {}
locals {
  partition = data.aws_partition.current.partition
  region    = data.aws_region.current.name

  # Private ECR Account IDs for EMR Spark Operator Helm Charts
  account_region_map = {
    ap-northeast-1 = "059004520145"
    ap-northeast-2 = "996579266876"
    ap-south-1     = "235914868574"
    ap-southeast-1 = "671219180197"
    ap-southeast-2 = "038297999601"
    ca-central-1   = "351826393999"
    eu-central-1   = "107292555468"
    eu-north-1     = "830386416364"
    eu-west-1      = "483788554619"
    eu-west-2      = "118780647275"
    eu-west-3      = "307523725174"
    sa-east-1      = "052806832358"
    us-east-1      = "755674844232"
    us-east-2      = "711395599931"
    us-west-1      = "608033475327"
    us-west-2      = "895885662937"
  }
}
